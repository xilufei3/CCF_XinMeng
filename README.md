# Dyslexia AI MVP Monorepo

读写困难家长咨询 MVP，前后端已合并在同一项目目录中：

- 后端 API（FastAPI + LangGraph 逻辑）：`src/`
- 前端咨询台（Next.js）：`frontend/`
- 一体化编排：`docker-compose.yml`

## 项目结构

```text
dyslexia-ai-mvp/
├── src/                    # FastAPI + scene logic
├── frontend/               # Next.js frontend (integrated)
├── data/                   # sqlite db files
├── logs/                   # runtime logs
├── docker-compose.yml      # api + frontend
├── Makefile                # unified dev/ops commands
└── .env(.example)          # backend env vars
```

## 快速开始（推荐 Docker）

1. 复制环境变量：

```bash
cp .env.example .env
```

2. 一键构建并启动：

```bash
make up
```

3. 访问地址：

- Frontend: `http://127.0.0.1:13000`
- API: `http://127.0.0.1:18080`

常用命令：

```bash
make ps
make logs
make down
```

## 本地开发（不使用 Docker）

1. 安装依赖：

```bash
make setup
```

2. 终端 A 启动后端：

```bash
make dev-api
```

3. 终端 B 启动前端：

```bash
make dev-frontend
```

默认本地访问：

- Frontend: `http://127.0.0.1:3000`
- API: `http://127.0.0.1:8000`

## 合并说明

本项目已将 `frontend` 作为后端项目内的子目录统一管理，不再作为独立仓库使用。

如果你需要重新构建前端容器并立即应用：

```bash
make rebuild-frontend
```

## API 范围

- `POST /chat`（SSE stream）
- `GET /history?device_id=...&process_id=...`
- `GET /healthz`
