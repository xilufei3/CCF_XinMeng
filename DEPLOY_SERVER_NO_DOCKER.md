# Dyslexia AI MVP 非 Docker 部署（极速版）

这份文档按“已拿到服务器”来写。先跑第 1 节，其他是补充。

默认端口：
- 前端：`9998`
- 后端：`18080`

## 1. 一次性上线（必跑，含 sqlite 检查 + RAG）

```bash
cd /opt/dyslexia-ai-mvp

# 首次是 clone，已有代码就用 git pull
git clone <你的仓库地址> . || git pull

cp .env.example .env
# 编辑 .env，至少配置：
# DEVICE_ID_SALT=...
# GLM_API_KEY=...（或 MODEL_API_KEY=...）
vim .env

python3 -m venv .venv
source .venv/bin/activate

pip install -U pip
pip install -r requirements.txt

# sqlite 版本必须 >= 3.35.0
python - <<'PY'
import sqlite3
print('sqlite:', sqlite3.sqlite_version)
PY

# 如果你看到版本 < 3.35.0，执行这段修复
pip install -U pysqlite3-binary
python - <<'PY'
import site, pathlib
p = pathlib.Path(site.getsitepackages()[0]) / 'sitecustomize.py'
p.write_text(
    "try:\n"
    "    import sys, pysqlite3\n"
    "    sys.modules['sqlite3'] = pysqlite3\n"
    "except Exception:\n"
    "    pass\n",
    encoding='utf-8',
)
print('written:', p)
PY

# 前端构建
cd /opt/dyslexia-ai-mvp/frontend
npm install
NEXT_PUBLIC_API_URL=/api NEXT_PUBLIC_ASSISTANT_ID=agent npm run build

# 回到根目录
cd /opt/dyslexia-ai-mvp
mkdir -p data logs chroma_db

# RAG 建库（必须）
python -m src.app.scripts.index_documents
```

启动服务：

```bash
# 终端1：后端
cd /opt/dyslexia-ai-mvp
source .venv/bin/activate
uvicorn src.app.main:app --host 0.0.0.0 --port 18080

# 终端2：前端
cd /opt/dyslexia-ai-mvp/frontend
NEXT_PUBLIC_API_URL=/api NEXT_PUBLIC_ASSISTANT_ID=agent ADAPTER_BACKEND_URL=http://127.0.0.1:18080 NEXT_TELEMETRY_DISABLED=1 npm run start -- --hostname 0.0.0.0 --port 9998
```

验证：

```bash
curl -sS http://127.0.0.1:18080/healthz
curl -I http://127.0.0.1:9998
ls -la /opt/dyslexia-ai-mvp/chroma_db
```

访问：
- `http://服务器IP:9998`

## 2. 日常更新

```bash
cd /opt/dyslexia-ai-mvp
git pull

source .venv/bin/activate
pip install -r requirements.txt

cd frontend
npm install
NEXT_PUBLIC_API_URL=/api NEXT_PUBLIC_ASSISTANT_ID=agent npm run build
cd ..

# docs 有变化时重建 RAG
# python -m src.app.scripts.index_documents
```

## 3. systemd（可选，推荐）

`/etc/systemd/system/dyslexia-api.service`

```ini
[Unit]
Description=Dyslexia AI MVP API
After=network.target

[Service]
Type=simple
User=<YOUR_USER>
WorkingDirectory=/opt/dyslexia-ai-mvp
ExecStart=/opt/dyslexia-ai-mvp/.venv/bin/uvicorn src.app.main:app --host 0.0.0.0 --port 18080
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/dyslexia-frontend.service`

```ini
[Unit]
Description=Dyslexia AI MVP Frontend
After=network.target dyslexia-api.service

[Service]
Type=simple
User=<YOUR_USER>
WorkingDirectory=/opt/dyslexia-ai-mvp/frontend
Environment=NEXT_PUBLIC_API_URL=/api
Environment=NEXT_PUBLIC_ASSISTANT_ID=agent
Environment=ADAPTER_BACKEND_URL=http://127.0.0.1:18080
Environment=NEXT_TELEMETRY_DISABLED=1
ExecStart=/usr/bin/npm run start -- --hostname 0.0.0.0 --port 9998
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable dyslexia-api dyslexia-frontend
sudo systemctl restart dyslexia-api dyslexia-frontend

systemctl status dyslexia-api --no-pager
systemctl status dyslexia-frontend --no-pager
```

## 4. 常见问题（最短排查）

问题：`sqlite` 版本不够（如 3.34.1）

```bash
source .venv/bin/activate
python - <<'PY'
import sqlite3
print(sqlite3.sqlite_version)
PY
```

如果 `< 3.35.0`：按第 1 节 `pysqlite3-binary + sitecustomize.py` 修复。

问题：页面能开但对话失败

```bash
# 看后端日志（手动启动时）
# 或 systemd 日志
journalctl -u dyslexia-api -f
```

重点检查：
- `.env` 是否有 `GLM_API_KEY` 或 `MODEL_API_KEY`
- `ADAPTER_BACKEND_URL` 是否是 `http://127.0.0.1:18080`
- 是否执行过 `python -m src.app.scripts.index_documents`

问题：服务器上只有整段回复，没有逐字流式

如果前面有 Nginx/宝塔反向代理，默认缓冲会破坏 SSE。需要关闭缓冲：

```nginx
location / {
    proxy_pass http://127.0.0.1:9998;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_request_buffering off;
    gzip off;
    chunked_transfer_encoding on;
    add_header X-Accel-Buffering no;
}
```
