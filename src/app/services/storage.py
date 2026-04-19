import json

import aiosqlite

from src.app.services.report_session import (
    GENERAL_SESSION_TYPE,
    HIDDEN_CLIENT_MSG_PREFIX,
    normalize_session_type,
)


CREATE_PROCESS_REGISTRY_SQL = """
CREATE TABLE IF NOT EXISTS process_registry (
  thread_id TEXT PRIMARY KEY,
  device_id_hash TEXT NOT NULL,
  process_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  session_type TEXT NOT NULL DEFAULT 'general',
  report_id TEXT,
  report_text TEXT,
  report_data_json TEXT,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(device_id_hash, process_id)
);
"""

CREATE_PROCESS_MESSAGES_SQL = """
CREATE TABLE IF NOT EXISTS process_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id TEXT NOT NULL,
  client_msg_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  cached INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(thread_id, client_msg_id, role)
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_messages_thread_created
ON process_messages(thread_id, created_at);
"""


async def _has_column(conn: aiosqlite.Connection, table_name: str, column_name: str) -> bool:
    cur = await conn.execute(f"PRAGMA table_info({table_name})")
    rows = await cur.fetchall()
    return any(len(row) > 1 and str(row[1]) == column_name for row in rows)


class Storage:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(CREATE_PROCESS_REGISTRY_SQL)
            await conn.execute(CREATE_PROCESS_MESSAGES_SQL)
            await conn.execute(CREATE_INDEX_SQL)

            # Lightweight migration path for existing local SQLite files.
            if not await _has_column(conn, "process_registry", "session_type"):
                await conn.execute(
                    "ALTER TABLE process_registry ADD COLUMN session_type TEXT NOT NULL DEFAULT 'general'"
                )
            if not await _has_column(conn, "process_registry", "report_id"):
                await conn.execute("ALTER TABLE process_registry ADD COLUMN report_id TEXT")
            if not await _has_column(conn, "process_registry", "report_text"):
                await conn.execute("ALTER TABLE process_registry ADD COLUMN report_text TEXT")
            if not await _has_column(conn, "process_registry", "report_data_json"):
                await conn.execute("ALTER TABLE process_registry ADD COLUMN report_data_json TEXT")

            await conn.commit()

    async def upsert_process(
        self,
        thread_id: str,
        device_id_hash: str,
        process_id: str,
        session_type: str | None = None,
        report_id: str | None = None,
        report_text: str | None = None,
    ) -> None:
        if session_type is None and report_id is None and report_text is None:
            sql = """
            INSERT INTO process_registry (thread_id, device_id_hash, process_id)
            VALUES (?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
              status = 'active',
              updated_at = CURRENT_TIMESTAMP
            """
            async with aiosqlite.connect(self.db_path) as conn:
                await conn.execute(sql, (thread_id, device_id_hash, process_id))
                await conn.commit()
            return

        normalized_session_type = normalize_session_type(session_type)
        normalized_report_text = str(report_text or "").strip() or None
        sql = """
        INSERT INTO process_registry (
          thread_id,
          device_id_hash,
          process_id,
          session_type,
          report_id,
          report_text,
          report_data_json
        )
        VALUES (?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(thread_id) DO UPDATE SET
          status = 'active',
          updated_at = CURRENT_TIMESTAMP,
          session_type = excluded.session_type,
          report_id = excluded.report_id,
          report_text = excluded.report_text,
          report_data_json = NULL
        """
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                sql,
                (
                    thread_id,
                    device_id_hash,
                    process_id,
                    normalized_session_type,
                    report_id,
                    normalized_report_text,
                ),
            )
            await conn.commit()

    async def get_process_context(self, thread_id: str) -> dict:
        sql = """
        SELECT session_type, report_id, report_text, report_data_json
        FROM process_registry
        WHERE thread_id = ?
        LIMIT 1
        """
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(sql, (thread_id,))
            row = await cur.fetchone()

        if row is None:
            return {
                "session_type": GENERAL_SESSION_TYPE,
                "report_id": None,
                "report_text": None,
            }

        report_text = str(row["report_text"] or "").strip() or None
        if report_text is None:
            # Backward-compatible fallback for older local rows that stored JSON.
            legacy_json = str(row["report_data_json"] or "").strip()
            if legacy_json:
                try:
                    parsed = json.loads(legacy_json)
                    if isinstance(parsed, dict) and isinstance(parsed.get("raw_text"), str):
                        report_text = parsed.get("raw_text", "").strip() or None
                    elif isinstance(parsed, str):
                        report_text = parsed.strip() or None
                except Exception:
                    report_text = None

        return {
            "session_type": normalize_session_type(str(row["session_type"] or "")),
            "report_id": str(row["report_id"]) if row["report_id"] is not None else None,
            "report_text": report_text,
        }

    async def find_cached_assistant(self, thread_id: str, client_msg_id: str) -> str | None:
        sql = """
        SELECT content
        FROM process_messages
        WHERE thread_id = ? AND client_msg_id = ? AND role = 'assistant' AND status = 'active'
        ORDER BY id DESC LIMIT 1
        """
        async with aiosqlite.connect(self.db_path) as conn:
            cur = await conn.execute(sql, (thread_id, client_msg_id))
            row = await cur.fetchone()
            return row[0] if row else None

    async def has_processing_user(self, thread_id: str, client_msg_id: str) -> bool:
        sql = """
        SELECT 1
        FROM process_messages
        WHERE thread_id = ? AND client_msg_id = ? AND role = 'user' AND status = 'processing'
        LIMIT 1
        """
        async with aiosqlite.connect(self.db_path) as conn:
            cur = await conn.execute(sql, (thread_id, client_msg_id))
            return await cur.fetchone() is not None

    async def insert_user_processing(self, thread_id: str, client_msg_id: str, content: str) -> None:
        sql = """
        INSERT INTO process_messages (thread_id, client_msg_id, role, content, status)
        VALUES (?, ?, 'user', ?, 'processing')
        """
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(sql, (thread_id, client_msg_id, content))
            await conn.commit()

    async def mark_user_active(self, thread_id: str, client_msg_id: str) -> None:
        sql = """
        UPDATE process_messages
        SET status = 'active', updated_at = CURRENT_TIMESTAMP
        WHERE thread_id = ? AND client_msg_id = ? AND role = 'user'
        """
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(sql, (thread_id, client_msg_id))
            await conn.commit()

    async def mark_user_error(self, thread_id: str, client_msg_id: str) -> None:
        sql = """
        UPDATE process_messages
        SET status = 'error', updated_at = CURRENT_TIMESTAMP
        WHERE thread_id = ? AND client_msg_id = ? AND role = 'user'
        """
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(sql, (thread_id, client_msg_id))
            await conn.commit()

    async def insert_assistant_active(
        self,
        thread_id: str,
        client_msg_id: str,
        content: str,
        cached: bool = False,
    ) -> None:
        sql = """
        INSERT OR IGNORE INTO process_messages
        (thread_id, client_msg_id, role, content, status, cached)
        VALUES (?, ?, 'assistant', ?, 'active', ?)
        """
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(sql, (thread_id, client_msg_id, content, int(cached)))
            await conn.commit()

    async def load_history(self, thread_id: str) -> list[dict]:
        sql = """
        SELECT role, content, created_at, client_msg_id
        FROM process_messages
        WHERE thread_id = ? AND status = 'active'
        ORDER BY id ASC
        """
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(sql, (thread_id,))
            rows = await cur.fetchall()
            return [dict(row) for row in rows]

    async def list_processes(self, device_id_hash: str, limit: int = 100, offset: int = 0) -> list[dict]:
        sql = """
        SELECT
          pr.process_id,
          pr.status,
          pr.session_type,
          pr.report_id,
          pr.created_at,
          pr.updated_at,
          (
            SELECT pm.content
            FROM process_messages pm
            WHERE pm.thread_id = pr.thread_id
              AND pm.role = 'user'
              AND pm.status = 'active'
              AND pm.client_msg_id NOT LIKE ?
            ORDER BY pm.id ASC
            LIMIT 1
          ) AS preview
        FROM process_registry pr
        WHERE pr.device_id_hash = ?
          AND pr.status = 'active'
        ORDER BY pr.updated_at DESC
        LIMIT ? OFFSET ?
        """
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(sql, (f"{HIDDEN_CLIENT_MSG_PREFIX}%", device_id_hash, limit, offset))
            rows = await cur.fetchall()
            return [dict(row) for row in rows]

    async def soft_delete_process(self, thread_id: str, device_id_hash: str) -> bool:
        check_sql = """
        SELECT 1
        FROM process_registry
        WHERE thread_id = ? AND device_id_hash = ?
        LIMIT 1
        """
        delete_process_sql = """
        UPDATE process_registry
        SET status = 'deleted', updated_at = CURRENT_TIMESTAMP
        WHERE thread_id = ? AND device_id_hash = ? AND status != 'deleted'
        """
        delete_messages_sql = """
        UPDATE process_messages
        SET status = 'deleted', updated_at = CURRENT_TIMESTAMP
        WHERE thread_id = ? AND status != 'deleted'
        """
        async with aiosqlite.connect(self.db_path) as conn:
            cur = await conn.execute(check_sql, (thread_id, device_id_hash))
            exists = await cur.fetchone() is not None
            if not exists:
                return False

            await conn.execute(delete_process_sql, (thread_id, device_id_hash))
            await conn.execute(delete_messages_sql, (thread_id,))
            await conn.commit()
            return True
