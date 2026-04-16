# Frontend (Integrated)

该目录是 `dyslexia-ai-mvp` 的前端子项目，不再作为独立仓库单独维护。

请优先使用根目录文档与命令：

- 根文档：`../README.md`
- 一键启动：`make up`
- 前端重建：`make rebuild-frontend`
- 本地开发：`make dev-frontend`

如需直接在本目录运行：

```bash
npm install
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 NEXT_PUBLIC_ASSISTANT_ID=agent npm run dev -- --hostname 0.0.0.0 --port 3000
```
