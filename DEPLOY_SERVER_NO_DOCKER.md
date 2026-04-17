# Dyslexia AI MVP 服务器非 Docker 部署手册（从零开始）

本文档用于在一台全新 Linux 服务器上，不使用 Docker，直接部署 `dyslexia-ai-mvp`。

部署形态：
- 后端：`FastAPI + uvicorn`（systemd 托管）
- 前端：`Next.js` 生产构建 + `next start`（systemd 托管）
- 访问方式：服务器 IP + 端口（不接域名、不接 HTTPS）

推荐端口：
- 前端：`13000`（对外访问）
- 后端：`18080`（建议仅本机/内网访问）

---

## 1. 前置条件

建议服务器配置：
- 2 vCPU
- 4 GB RAM
- 20 GB 磁盘

需要的软件：
- Python 3.11+
- Node.js 24（与项目 Dockerfile 对齐）
- npm（Node 自带）
- git

---

## 2. 安装系统依赖

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates gnupg lsb-release build-essential python3 python3-venv python3-pip
```

---

## 3. 安装 Node.js 24

```bash
curl -fsSL https://deb.nodesource.com/setup_24.x | sudo -E bash -
sudo apt-get install -y nodejs
node -v
npm -v
```

---

## 4. 拉取项目代码

```bash
sudo mkdir -p /opt/dyslexia-ai-mvp
sudo chown -R $USER:$USER /opt/dyslexia-ai-mvp
cd /opt/dyslexia-ai-mvp
git clone <你的仓库地址> .
```

后续更新：

```bash
cd /opt/dyslexia-ai-mvp
git pull
```

---

## 5. 配置环境变量

复制并编辑 `.env`：

```bash
cd /opt/dyslexia-ai-mvp
cp .env.example .env
vim .env
```

至少确认以下项：
- `DEVICE_ID_SALT`：替换默认值
- `MODEL_API_BASE`：按你的模型供应商设置
- `GLM_API_KEY` 或 `MODEL_API_KEY`：至少配置一个

说明：
- 项目已兼容：`GLM_API_KEY` 优先，`MODEL_API_KEY` 兜底

---

## 6. 安装后端依赖（Python）

```bash
cd /opt/dyslexia-ai-mvp
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate
```

---

## 7. 安装并构建前端（Node）

```bash
cd /opt/dyslexia-ai-mvp/frontend
npm install
NEXT_PUBLIC_API_URL=/api NEXT_PUBLIC_ASSISTANT_ID=agent npm run build
```

说明：
- `NEXT_PUBLIC_API_URL=/api`：前端统一走内置 `/api` 适配层
- 前端服务端代理地址由运行时变量 `ADAPTER_BACKEND_URL` 控制（后续 systemd 会配置）

---

## 8. 准备运行目录

```bash
cd /opt/dyslexia-ai-mvp
mkdir -p data logs chroma_db
```

---

## 9. 先手动启动验证（建议）

### 9.1 启动后端（终端1）

```bash
cd /opt/dyslexia-ai-mvp
source .venv/bin/activate
uvicorn src.app.main:app --host 0.0.0.0 --port 18080
```

### 9.2 启动前端（终端2）

```bash
cd /opt/dyslexia-ai-mvp/frontend
NEXT_PUBLIC_API_URL=/api \
NEXT_PUBLIC_ASSISTANT_ID=agent \
ADAPTER_BACKEND_URL=http://127.0.0.1:18080 \
NEXT_TELEMETRY_DISABLED=1 \
npm run start -- --hostname 0.0.0.0 --port 13000
```

### 9.3 验证

```bash
curl -sS http://127.0.0.1:18080/healthz
curl -I http://127.0.0.1:13000
```

浏览器打开：
- `http://服务器IP:13000`

---

## 10. 配置 systemd（生产建议）

下面配置会让服务开机自启、崩溃自动拉起。

### 10.1 后端服务

创建文件：

```bash
sudo vim /etc/systemd/system/dyslexia-api.service
```

写入：

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

> 注意：把 `User=<YOUR_USER>` 改成你的实际用户名，例如 `User=ubuntu` 或 `User=yupeng`。

### 10.2 前端服务

创建文件：

```bash
sudo vim /etc/systemd/system/dyslexia-frontend.service
```

写入：

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
ExecStart=/usr/bin/npm run start -- --hostname 0.0.0.0 --port 13000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

> 同样把 `User=<YOUR_USER>` 改成实际用户名。

### 10.3 启动与自启

```bash
sudo systemctl daemon-reload
sudo systemctl enable dyslexia-api
sudo systemctl enable dyslexia-frontend
sudo systemctl start dyslexia-api
sudo systemctl start dyslexia-frontend
```

查看状态与日志：

```bash
systemctl status dyslexia-api --no-pager
systemctl status dyslexia-frontend --no-pager
journalctl -u dyslexia-api -f
journalctl -u dyslexia-frontend -f
```

---

## 11. 防火墙建议（端口直连）

如果使用 `ufw`：

```bash
sudo ufw allow 22/tcp
sudo ufw allow 13000/tcp
```

`18080` 处理建议：
- 若只给前端代理用，不需要外网调试：不开放 `18080`
- 需要外网直连后端调试：再开放 `18080/tcp`

---

## 12. RAG 索引（可选但常用）

资料放到仓库 `docs/` 后执行：

```bash
cd /opt/dyslexia-ai-mvp
source .venv/bin/activate
python -m src.app.scripts.index_documents
deactivate
```

---

## 13. 代码更新与发布

```bash
cd /opt/dyslexia-ai-mvp
git pull

# 后端依赖有变化时执行
source .venv/bin/activate
pip install -r requirements.txt
deactivate

# 前端代码有变化时执行
cd frontend
npm install
NEXT_PUBLIC_API_URL=/api NEXT_PUBLIC_ASSISTANT_ID=agent npm run build
cd ..

sudo systemctl restart dyslexia-api
sudo systemctl restart dyslexia-frontend
```

---

## 14. 常见问题排查

问题：前端页面打开但对话报错  
排查：
1. `systemctl status dyslexia-api` 是否正常运行。
2. `journalctl -u dyslexia-api -f` 是否出现 API key 缺失。
3. `.env` 中是否配置 `GLM_API_KEY` 或 `MODEL_API_KEY`。
4. 前端服务里 `ADAPTER_BACKEND_URL` 是否指向 `http://127.0.0.1:18080`。

问题：后端启动失败（ModuleNotFound / import error）  
排查：
1. 是否在 `/opt/dyslexia-ai-mvp` 下创建了 `.venv`。
2. 是否执行了 `pip install -r requirements.txt`。
3. `WorkingDirectory` 是否正确。

问题：更新后前端未生效  
排查：
1. 是否执行了 `npm run build`。
2. 是否 `systemctl restart dyslexia-frontend`。
3. 是否浏览器缓存未刷新（强刷）。

---

## 15. 最小上线命令（速查）

```bash
cd /opt/dyslexia-ai-mvp
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
deactivate

cd frontend
npm install
NEXT_PUBLIC_API_URL=/api NEXT_PUBLIC_ASSISTANT_ID=agent npm run build

cd /opt/dyslexia-ai-mvp
mkdir -p data logs chroma_db
```

手动启动：

```bash
# API
cd /opt/dyslexia-ai-mvp
source .venv/bin/activate
uvicorn src.app.main:app --host 0.0.0.0 --port 18080

# FE（新终端）
cd /opt/dyslexia-ai-mvp/frontend
NEXT_PUBLIC_API_URL=/api NEXT_PUBLIC_ASSISTANT_ID=agent ADAPTER_BACKEND_URL=http://127.0.0.1:18080 NEXT_TELEMETRY_DISABLED=1 npm run start -- --hostname 0.0.0.0 --port 13000
```
