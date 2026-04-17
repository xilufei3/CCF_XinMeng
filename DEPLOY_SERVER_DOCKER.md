# Dyslexia AI MVP 服务器 Docker 部署手册（从零开始）

本文档用于在一台全新 Linux 服务器上，以端口直连方式部署 `dyslexia-ai-mvp`。

适用范围：
- Ubuntu 22.04 / 24.04（Debian 系同理）
- Docker + Docker Compose Plugin
- 不接入域名与 HTTPS，直接使用服务器 IP + 端口访问

当前项目默认端口：
- 前端：`13000`（外部访问入口）
- 后端：`18080`（调试可访问，可按需不对公网开放）

---

## 1. 部署前准备

你需要准备：
- 一台可 SSH 登录的 Linux 服务器
- 服务器具备公网 IP（或可从你的网络访问）
- 一个可用的模型 API Key（支持 `GLM_API_KEY` 或 `MODEL_API_KEY`）

建议最低配置：
- 2 vCPU
- 4 GB RAM
- 20 GB 磁盘

---

## 2. 服务器初始化

以 `root` 或有 sudo 权限用户登录服务器后执行：

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release git
```

创建项目目录：

```bash
sudo mkdir -p /opt/dyslexia-ai-mvp
sudo chown -R $USER:$USER /opt/dyslexia-ai-mvp
cd /opt/dyslexia-ai-mvp
```

---

## 3. 安装 Docker 与 Compose

```bash
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

将当前用户加入 docker 组（可省去每次 sudo）：

```bash
sudo usermod -aG docker $USER
newgrp docker
docker --version
docker compose version
```

---

## 4. 拉取项目代码

在 `/opt/dyslexia-ai-mvp` 下执行：

```bash
git clone <你的仓库地址> .
```

如果目录已是 git 仓库，后续更新使用：

```bash
git pull
```

---

## 5. 配置环境变量

复制模板：

```bash
cp .env.example .env
```

编辑：

```bash
vim .env
```

至少确认以下变量：
- `DEVICE_ID_SALT`：请替换默认值，使用随机字符串
- `MODEL_API_BASE`：按你的模型服务商配置
- `GLM_API_KEY` 或 `MODEL_API_KEY`：至少配置一个

说明：
- 项目已兼容以下优先级读取：
  - `GLM_API_KEY` 优先
  - `MODEL_API_KEY` 兜底
- 推荐只保留一个，避免维护歧义

生成随机盐示例：

```bash
openssl rand -base64 48
```

---

## 6. 启动服务（首次部署）

创建持久化目录并启动：

```bash
mkdir -p data logs chroma_db
docker compose up -d --build
```

检查服务状态：

```bash
docker compose ps
docker compose logs -f --tail=200
```

---

## 7. 访问与健康检查

后端健康检查：

```bash
curl -sS http://127.0.0.1:18080/healthz
```

预期返回：

```json
{"status":"ok"}
```

浏览器访问：
- `http://服务器IP:13000`

---

## 8. 防火墙与端口策略（端口直连）

如果使用 `ufw`，建议：

```bash
sudo ufw allow 22/tcp
sudo ufw allow 13000/tcp
```

是否开放 `18080`：
- 需要直接调试后端接口：开放 `18080/tcp`
- 不需要外部直连后端：不要开放 `18080`

---

## 9. RAG 文档索引（可选但常用）

当你在仓库 `docs/` 下新增/替换资料后，执行：

```bash
docker compose exec api python -m src.app.scripts.index_documents
```

检查向量库目录：

```bash
ls -la chroma_db
```

说明：
- 向量库持久化在宿主机 `./chroma_db`
- 若文档源变更，建议重新执行索引命令

---

## 10. 开机自启动与稳定性

建议为两个容器设置自动重启策略：

```bash
docker update --restart unless-stopped dyslexia-ai-mvp-api dyslexia-ai-mvp-frontend
```

服务器重启后验证：

```bash
docker ps
```

---

## 11. 日常运维命令

查看状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f --tail=200
```

重启服务：

```bash
docker compose restart
```

停止服务：

```bash
docker compose down
```

---

## 12. 代码更新与重新部署

```bash
cd /opt/dyslexia-ai-mvp
git pull
docker compose up -d --build
```

若仅修改后端代码：

```bash
docker compose up -d --build api
```

若仅修改前端代码：

```bash
docker compose up -d --build frontend
```

---

## 13. 备份与回滚

建议定期备份：
- `.env`
- `data/`
- `chroma_db/`
- `logs/`

备份示例：

```bash
cd /opt/dyslexia-ai-mvp
tar czf backup-$(date +%F-%H%M).tgz .env data chroma_db logs
```

回滚示例（按 git 版本）：

```bash
cd /opt/dyslexia-ai-mvp
git checkout <commit_or_tag>
docker compose up -d --build
```

---

## 14. 常见问题排查

问题：前端能打开但对话失败  
排查：
1. `docker compose ps` 确认 `api` 容器正常运行。
2. `docker compose logs -f api` 查看是否有 API Key 缺失报错。
3. `.env` 检查是否配置了 `GLM_API_KEY` 或 `MODEL_API_KEY`。

问题：`/healthz` 不通  
排查：
1. 先在服务器本机执行 `curl http://127.0.0.1:18080/healthz`。
2. 若本机通、外网不通，检查云安全组/防火墙端口策略。
3. 检查 `docker compose ps` 的端口映射是否存在 `18080:8000`。

问题：RAG 没有检索结果  
排查：
1. 确认已执行 `python -m src.app.scripts.index_documents`。
2. 确认 `RETRIEVAL_ENABLED=true`。
3. 检查 `CHROMA_PERSIST_DIR` 是否与挂载目录一致（默认 `./chroma_db`）。

---

## 15. 一键最小上线命令（速查）

```bash
cd /opt/dyslexia-ai-mvp
cp .env.example .env
vim .env
mkdir -p data logs chroma_db
docker compose up -d --build
docker compose ps
curl -sS http://127.0.0.1:18080/healthz
```

前端访问：`http://服务器IP:13000`
