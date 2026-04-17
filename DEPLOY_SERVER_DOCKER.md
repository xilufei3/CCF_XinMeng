# Dyslexia AI MVP Docker 部署（极速版）

这份文档按“已经拿到服务器”来写。先跑第 1 节，其他都是补充。

默认端口：
- 前端：`9998`
- 后端：`18080`

## 1. 一次性上线（必跑，含 RAG）

```bash
cd /opt/dyslexia-ai-mvp

# 首次是 clone，已有代码就用 git pull
git clone <你的仓库地址> . || git pull

cp .env.example .env
# 编辑 .env，至少配置：
# DEVICE_ID_SALT=...
# GLM_API_KEY=...（或 MODEL_API_KEY=...）
vim .env

mkdir -p data logs chroma_db

docker compose up -d --build

# 健康检查
curl -sS http://127.0.0.1:18080/healthz

# RAG 建库（必须）
docker compose exec api python -m src.app.scripts.index_documents

# 验证向量库已生成
docker compose exec api ls -la /app/chroma_db
```

访问：
- `http://服务器IP:9998`

## 2. 日常更新

```bash
cd /opt/dyslexia-ai-mvp
git pull
docker compose up -d --build

# 文档有变化时，重新索引
# docker compose exec api python -m src.app.scripts.index_documents
```

## 3. 常用命令

```bash
# 状态
docker compose ps

# 日志
docker compose logs -f --tail=200

# 重启
docker compose restart

# 停止
docker compose down
```

## 4. 防火墙建议（端口直连）

如果使用 `ufw`：

```bash
sudo ufw allow 22/tcp
sudo ufw allow 9998/tcp
```

`18080` 是否开放：
- 要公网调试后端：开放 `18080/tcp`
- 不需要：不要开放 `18080`

## 5. 常见问题（最短排查）

问题：页面打开但无法对话

```bash
docker compose ps
docker compose logs --tail=200 api
```

重点检查：
- `.env` 是否有 `GLM_API_KEY` 或 `MODEL_API_KEY`
- 是否执行过 `python -m src.app.scripts.index_documents`

问题：RAG 报未初始化

```bash
docker compose exec api python -m src.app.scripts.index_documents
docker compose exec api ls -la /app/chroma_db
```

问题：服务器上只有整段回复，没有逐字流式

如果前面有 Nginx/宝塔反向代理，必须关闭缓冲。示例：

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

## 6. 可选：容器自动拉起

```bash
docker update --restart unless-stopped dyslexia-ai-mvp-api dyslexia-ai-mvp-frontend
```

## 7. 附录：机器还没装 Docker 时

只在“服务器没有 Docker”时执行：

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release git

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```
