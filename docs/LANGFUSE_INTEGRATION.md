# Langfuse 接入流程

本项目已按 Langfuse 官方 LangChain 集成方式接入:

- 使用 `langfuse.langchain.CallbackHandler`
- 通过 LangChain/LangGraph `config` 传递 `callbacks`
- 使用 `metadata` 传递 `langfuse_session_id`、`langfuse_user_id`、`langfuse_tags`

## 1. 安装依赖

```bash
pip install -r requirements.txt
```

## 2. 配置环境变量

在 `.env` 中设置:

```env
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

如果是自建 Langfuse, 请把 `LANGFUSE_BASE_URL` 改为你的服务地址。

## 3. 启动项目

应用启动后会尝试初始化 Langfuse:

- 若 `LANGFUSE_ENABLED=true` 且 key 完整且依赖可用: 启用 tracing
- 若未配置 key 或依赖缺失: 自动降级为关闭 tracing（不影响主流程）
- 若 `LANGFUSE_ENABLED=false`: 强制关闭 tracing（即使 key 已配置）

## 4. Trace 结构

每次对话 run 会上报以下信息:

- `langfuse_session_id`: 当前 `thread_id`
- `langfuse_user_id`: 当前 `device_id_hash`
- `langfuse_tags`: 会话类型标签（如 `general`/`report`）与 `chat`
- 额外 metadata: `web_search_enabled`、`prompt_version`

## 5. 关闭与刷新

服务退出阶段会执行 `flush`，尽量确保尾部 trace 上报完成。
