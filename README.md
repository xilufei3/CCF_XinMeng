# Dyslexia AI MVP Monorepo

读写困难家长咨询 MVP，前后端合并在同一项目目录中：

- 后端 API（FastAPI + LangGraph + LangChain）：`src/`
- 前端咨询台（Next.js）：`frontend/`
- 一体化编排：`docker-compose.yml`

## 项目结构

```text
dyslexia-ai-mvp/
├── src/
│   └── app/
│       ├── api/                    # FastAPI 路由
│       ├── graph/                  # LangGraph 状态机与节点
│       │   ├── nodes/
│       │   │   ├── intake.py
│       │   │   ├── route.py
│       │   │   ├── retrieve.py
│       │   │   └── llm_response.py
│       │   ├── state.py
│       │   └── workflow.py
│       ├── prompts/                # workflow.yaml prompt 常量
│       ├── scripts/
│       │   └── index_documents.py  # docs/ 离线索引到 Chroma
│       └── services/
│           ├── llm.py
│           ├── retriever.py
│           └── chat_service.py
├── docs/                           # 专业资料(pdf/md/docx)
├── data/                           # sqlite db files
├── logs/                           # runtime logs
├── tests/                          # pytest
├── workflow.yaml
└── requirements.txt
```

## 快速开始（推荐 Docker）

1. 复制环境变量

```bash
cp .env.example .env
```

2. 一键构建并启动

```bash
make up
```

3. 访问地址

- Frontend: `http://127.0.0.1:13000`
- API: `http://127.0.0.1:18080`

常用命令：

```bash
make ps
make logs
make down
```

## 本地开发（不使用 Docker）

1. 安装依赖

```bash
make setup
```

2. 启动后端

```bash
make dev-api
```

3. 启动前端

```bash
make dev-frontend
```

默认本地访问：

- Frontend: `http://127.0.0.1:3000`
- API: `http://127.0.0.1:8000`

## 文档索引（RAG）

把专业资料放入 `docs/` 后执行：

```bash
python -m src.app.scripts.index_documents
```

脚本会：

- 加载 `docs/` 下 `pdf/md/docx`
- 使用 `RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)` 切片
- 写入 Chroma（`settings.chroma_persist_dir`）

## RAG 严格模式

`src/app/services/retriever.py` 的 `get_retriever()` 工厂逻辑如下：

- `retrieval_enabled=false`：直接抛错
- Chroma 目录未就绪（未索引或空目录）：直接抛错
- Chroma 初始化失败：直接抛错
- 全部正常时：返回 `Chroma(...).as_retriever(k=retrieval_top_k)`

建议配置项（`.env`）：

- `RETRIEVAL_ENABLED=true`
- `CHROMA_PERSIST_DIR=./chroma_db`
- `COLLECTION_NAME=xingmeng_docs`
- `RETRIEVAL_TOP_K=3`
- `EMBEDDING_MODEL_NAME=embedding-3`

## 流式输出

`POST /chat` 保持 SSE text chunk 协议。

后端使用 `graph.astream_events(version="v2")`，并只透传 `langgraph_node == "llm_response"` 的 `on_chat_model_stream` token，避免 route 节点内部调用泄露到前端。

## 测试

运行：

```bash
pytest -q
```

覆盖范围：

- route 节点结构化输出与报错行为
- retrieve 节点固定检索与报错行为
- `_format_docs` 组装
- 图级端到端分支与最终状态字段

## API 范围

- `POST /chat`（SSE stream）
- `GET /history?device_id=...&process_id=...`
- `GET /healthz`
