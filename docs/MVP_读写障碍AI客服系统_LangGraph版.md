# 读写障碍 AI 客服系统 MVP 文档（LangGraph 版）

版本：V1.0  
日期：2026-04-14  
适用范围：MVP（首版上线）  
文档目标：统一产品、后端、前端、运营对 MVP 边界与实现方案的理解，支持 5 天内可演示、可恢复、可扩展的最小闭环交付。

---

## 1. 项目目标与定位

### 1.1 目标用户
- 家长（孩子存在阅读/书写困难，主动寻找解释和帮助的主要监护者）

### 1.2 核心业务目标
- 信任建立 -> 认知教育 -> 情绪缓解 -> 引导预约咨询

### 1.3 MVP 转化动作
- 在对话内条件触发“预约咨询引导”，由人工后续跟进。

### 1.4 明确不做
- 不做医疗诊断
- 不替代专业评估与干预
- 不直接售卖课程/报价
- 不做主动外呼/短信推送

---

## 2. MVP 范围（本期交付）

### 2.1 必做功能
- 多轮对话（SSE 流式输出）
- 基于 LangGraph 的场景路由与状态流转
- 对话过程持久化（process + message + checkpoint）
- 基于 `device_id + process_id` 的会话隔离和恢复
- 并发串行控制（同一 thread 串行，不同 thread 并行）
- 幂等保障（`thread_id + client_msg_id`）
- 预约咨询触发（仅在规则满足时软植入）

### 2.2 暂不纳入 MVP
- RAG 知识库检索
- 知识库运营后台
- 游戏化筛查模块
- 多实例分布式锁生产化（先保留设计）

---

## 3. 总体架构

### 3.1 技术栈
- 前端：Gradio ChatInterface
- 后端：FastAPI（SSE）
- 对话编排：LangGraph
- 模型调用：LangChain Chat Model（可配置供应商）
- 持久化：SQLite（MVP）
- 图状态快照：LangGraph AsyncSqliteSaver
- 部署：Docker Compose（单机单进程）

### 3.2 逻辑分层
- 接入层：`/chat`、`/history`、`/resume`
- 编排层：LangGraph 场景图
- 策略层：意图分类、焦虑评分、推销触发
- 存储层：SQLite 业务库 + Checkpoint 库

---

## 4. ID 体系与会话隔离

### 4.1 四类 ID 定义
- `device_id`：设备级稳定标识（客户端持久化）
- `process_id`：一次对话流程 ID（新对话生成）
- `client_msg_id`：消息级 ID（重试复用）
- `thread_id`：服务端拼接，`device_id_hash:process_id`

### 4.2 关键规则
- 客户端只传 `device_id + process_id + client_msg_id`
- 服务端计算 `thread_id`，客户端不直接控制
- 幂等键为 `UNIQUE(thread_id, client_msg_id)`

### 4.3 安全约束
- `device_id` 入库前做服务端盐化哈希（`device_id_hash`）
- 外部查询接口不直接暴露原始 `thread_id`

---

## 5. LangGraph 业务状态机

### 5.1 节点拓扑
- `START -> intake -> router -> scene_node -> sales_gate -> persist -> END`

### 5.2 场景节点（scene_node）
- `knowledge`：知识科普
- `emotion`：情绪承接
- `advice`：家庭干预建议
- `service`：服务咨询回答（不自动推销）
- `offtopic`：闲聊回收
- `crisis`：高风险安全兜底

### 5.3 路由逻辑
- 每轮先分类意图，再生成场景回复
- 焦虑分 >= 70：优先走 `emotion`
- 高风险关键词命中：强制走 `crisis`
- `sales_gate` 在所有场景后统一判定，避免节点内混入营销逻辑

---

## 6. 业务模块逻辑（按你提供的业务文档固化）

### 6.1 F1 意图识别与话题管控
- 识别类型：`knowledge / emotion / advice / service / offtopic / crisis`
- 越界处理：无关话题只一句话引导回主线，不深入
- 边界话题（ADHD、学校沟通）归入主流程处理，不单列模块

### 6.2 F2 科普与情绪疏导
- 先共情后科普
- 不使用诊断语气
- 遇误解触发纠偏（如“多练就好”“长大自然好”等）

### 6.3 F3 家庭干预建议
- 触发：家长主动描述具体困难并求方法
- 输出：每次 2-3 条，固定“三段式”
  - 场景
  - 做法
  - 为什么有用
- 信息不足：先问 1 个关键澄清问题，再给通用建议

### 6.4 F4 预约咨询转化
- 仅在三条件同时满足时触发（详见第 8 章）
- 每个 session 最多触发一次
- 软植入，不硬广，不恐吓

---

## 7. Prompt 设计（MVP 可直接使用）

### 7.1 全局 System Prompt
```text
你是“星萌小助手”，服务对象是担心孩子读写困难的家长。
目标是提供情绪支持、认知科普和家庭可执行建议，并在合适时机引导预约咨询。
必须遵守：
1) 不做医疗诊断，不承诺治疗结果。
2) 语气温和、平易近人、非评判。
3) 每次最多提供3条建议，必须具体、今天可执行。
4) 信息不足时，优先提出1个关键澄清问题。
5) 不说“你必须/你应该”，改用建议式表达。
6) 结尾附：
“以上内容仅供参考，不构成任何医疗诊断。如您关心孩子的具体情况，建议进行专业评估。”
```

### 7.2 路由 Prompt（结构化输出）
```json
{
  "intent": "knowledge|emotion|advice|service|offtopic|crisis",
  "anxiety_delta": -10,
  "intervention_intent": false,
  "risk_level": "low|medium|high",
  "reason": "一句话"
}
```

说明：
- `anxiety_delta` 范围 `[-10, +10]`
- `intervention_intent=true` 表示当轮出现干预/求助意愿

### 7.3 场景回复 Prompt 约束
- `knowledge`：先结论，再 2-3 个关键解释，避免术语堆砌
- `emotion`：先承接感受，再给可执行一步
- `advice`：2-3 条“三段式”建议，不做诊断
- `service`：回答服务信息，不默认推销
- `offtopic`：一句回应 + 拉回主线
- `crisis`：安全优先，停止营销，建议联系线下紧急支持

---

## 8. 焦虑评分与转化触发

### 8.1 会话状态字段
- `anxiety_score`：0-100，初始 50
- `consecutive_non_rise`：连续未上升轮次
- `intervention_intent`：当轮是否表达干预意愿
- `sales_triggered`：本会话是否已触发过转化

### 8.2 更新规则
- 每轮结束后：`anxiety_score = clamp(0,100, anxiety_score + anxiety_delta)`
- 若本轮分数 `<=` 上轮：`consecutive_non_rise +1`，否则归零

### 8.3 销售触发规则
仅当以下三项均满足：
1. `consecutive_non_rise >= 3`
2. `intervention_intent == true`
3. `sales_triggered == false`

触发后：
- 在正常回复末尾增加“可选咨询引导卡片”
- 将 `sales_triggered` 置为 `true`

---

## 9. 并发、幂等与恢复

### 9.1 幂等设计
- 幂等键：`(thread_id, client_msg_id)`
- 命中已完成记录：直接返回缓存（`cached=true`）
- 命中处理中记录：返回 `202 Accepted`，客户端重连同一 `client_msg_id`

### 9.2 并发控制（MVP）
- 单进程 `asyncio.Lock` 注册表
- 粒度：`thread_id`
- 同一 thread 串行；不同 thread 并行

### 9.3 崩溃恢复
- LangGraph checkpoint 按节点自动存档
- 启动后台扫尾任务，每 30 秒扫描超时 `processing`
- 从最近 checkpoint 恢复；超过重试上限置 `error`

### 9.4 部署前提
- MVP 阶段固定单进程运行（例如 `uvicorn --workers 1`）
- 多实例扩展时替换为 Redis 分布式锁

---

## 10. 数据库模型（MVP 最小集）

### 10.1 `process_registry`
- `thread_id` TEXT PRIMARY KEY
- `device_id_hash` TEXT NOT NULL
- `process_id` TEXT NOT NULL
- `anxiety_score` INTEGER NOT NULL DEFAULT 50
- `consecutive_non_rise` INTEGER NOT NULL DEFAULT 0
- `sales_triggered` INTEGER NOT NULL DEFAULT 0
- `status` TEXT NOT NULL DEFAULT 'active'
- `last_checkpoint_id` TEXT NULL
- `updated_at` TIMESTAMP
- `created_at` TIMESTAMP
- `UNIQUE(device_id_hash, process_id)`

### 10.2 `process_messages`
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `thread_id` TEXT NOT NULL
- `client_msg_id` TEXT NOT NULL
- `role` TEXT NOT NULL (`user|assistant|system`)
- `scene` TEXT NULL
- `intent_tag` TEXT NULL
- `content` TEXT NOT NULL
- `status` TEXT NOT NULL DEFAULT 'active' (`processing|active|error`)
- `cached` INTEGER NOT NULL DEFAULT 0
- `created_at` TIMESTAMP
- `updated_at` TIMESTAMP
- `UNIQUE(thread_id, client_msg_id, role)`
- 索引：`idx_messages_thread_created(thread_id, created_at)`

说明：
- 可选增加 `request_id` 将 user/assistant 成对关联，便于审计。

---

## 11. 接口定义

### 11.1 `POST /chat`
请求字段：
- `device_id` string
- `process_id` string
- `client_msg_id` string
- `message` string

响应：SSE
- `data: {"text":"..."}` 逐 token
- `data: {"cached": true, "text":"..."}` 幂等命中
- `data: {"error":"..."}` 异常
- `data: [DONE]` 结束

状态码：
- `200` 正常流式开始
- `200(cached)` 缓存命中
- `202` 首次请求仍 processing
- `408` 执行超时
- `500` 服务异常

### 11.2 `GET /history`
查询参数：
- `device_id`
- `process_id`

返回：
- 指定流程 `status=active` 的历史消息（按时间升序）

### 11.3 `POST /resume`（可选）
- 显式触发恢复指定流程，用于管理端排障

---

## 12. 输出规范与合规约束

### 12.1 必带免责声明
每条助手回复末尾必须附加：
- “以上内容仅供参考，不构成任何医疗诊断。如您关心孩子的具体情况，建议进行专业评估。”

### 12.2 禁止项
- 禁止诊断结论
- 禁止替代专业方案
- 禁止贬损学校/老师/机构
- 禁止恐吓式营销

### 12.3 语气规范
- 温和、平实、非评判
- 使用建议式表达，不命令家长

---

## 13. 典型会话路径（验收样例）

1. 用户：我孩子总看错字，是不是有问题？
- 路由：`knowledge`
- 输出：解释常见表现，强调需专业评估

2. 用户：老师总说他不认真，我真的很累
- 路由：`emotion`
- 输出：先承接情绪，再给沟通建议

3. 用户：我在家能怎么帮他？
- 路由：`advice`
- 输出：2-3 条家庭可执行建议

4. 用户：有更专业的帮助吗？
- 路由：`service`
- 若满足触发条件 -> `sales_gate` 追加预约引导

---

## 14. 非功能与观测指标

### 14.1 性能目标
- 首 token 延迟 <= 1.5s
- 完整回复 P90 <= 8s
- 支持 >= 50 并发会话（单机基线压测）

### 14.2 稳定性目标
- 崩溃后可从 checkpoint 恢复
- 重启后历史数据不丢失

### 14.3 关键指标埋点
- `idempotency_hit_rate`
- `lock_wait_ms_p95`
- `processing_timeout_count`
- `checkpoint_resume_success_rate`
- `sales_trigger_rate`
- `offtopic_redirect_rate`

---

## 15. 测试与验收清单

### 15.1 功能验收
- 30 条样本问句意图识别准确率 >= 85%
- 场景回复格式符合约束
- 推销触发“每 session 最多一次”
- 无关话题可被礼貌拉回

### 15.2 幂等与并发验收
- 同一 `client_msg_id` 重试不重复执行
- 同一 `thread_id` 并发提交无乱序
- 不同 `thread_id` 可并行执行

### 15.3 恢复验收
- 执行中强杀进程后可恢复到最近 checkpoint
- 超时请求可被扫尾任务回收为 `active` 或 `error`

---

## 16. 5 天交付计划

- Day 1（2026-04-14）：FastAPI + LangGraph 骨架、基础 `/chat`
- Day 2（2026-04-15）：SSE 流式 + SQLite + `/history`
- Day 3（2026-04-16）：场景路由与 Prompt 落地（无 RAG）
- Day 4（2026-04-17）：焦虑评分 + 转化触发 + 幂等/锁
- Day 5（2026-04-18）：崩溃恢复、联调、Demo 验收

---

## 17. 风险与缓解

- 风险：意图误判导致回复风格不稳定  
  缓解：加入规则兜底（高风险优先、焦虑高优先情绪承接）

- 风险：单进程锁在扩容后失效  
  缓解：明确 MVP 单进程，迭代一切 Redis 分布式锁

- 风险：营销时机不准确引发反感  
  缓解：严格三条件触发，运营审核话术模板

- 风险：模型输出标签不规范  
  缓解：JSON schema 校验 + 失败回退默认场景

---

## 18. 附录：MVP 边界速查

可做：
- 读写障碍科普
- 家庭基础陪伴建议
- 情绪承接
- 条件触发预约咨询

不可做：
- 医疗诊断
- 专业干预替代
- 直接报价成交
- 主动营销触达

