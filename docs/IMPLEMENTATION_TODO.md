# Implementation TODO (After Scaffold)

## 1) Replace rule-based router with LLM router
- File: `src/app/services/scene_logic.py`
- Implement structured JSON output:
  - intent
  - anxiety_delta
  - intervention_intent
  - risk_level
- Add strict schema validation and fallback route.

## 2) Introduce real prompt packs
- File: `src/app/services/prompts.py`
- Add scene-specific prompt templates aligned with business docs.
- Support prompt versioning for audit.

## 3) LangGraph checkpoint persistence
- File: `src/app/graph/workflow.py`
- Add optional checkpointer (SQLite/Postgres) behind config flag.
- Use `configurable.thread_id` as checkpoint key.

## 4) Resume and sweeper jobs
- New file: `src/app/services/recovery.py`
- Add periodic scan for stale `processing` records.
- Resume from latest checkpoint and mark final status.

## 5) Improve SSE semantics
- Keep current event shape but add event types:
  - token
  - cached
  - processing
  - error
  - done

## 6) Add tests
- Unit:
  - id utils
  - sales gate rules
  - idempotency behavior
- Integration:
  - `/chat` retry with same `client_msg_id`
  - same-thread serialization
  - history restoration
