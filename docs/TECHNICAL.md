# 技术设计与扩展指南

## 1. 模块依赖

```text
Vue -> FastAPI composition -> MonitorService
                              ├─ ProductSource -> SyntheticSource
                              ├─ RateGate -> local / Redis
                              ├─ Store -> SQLAlchemy -> SQLite / MySQL
                              ├─ MemoryService -> workflow/memory/revocation
                              └─ AgentRuntime -> LangGraph -> SuggestionModel
MCP JSON-RPC -> ToolGateway -> scoped read / candidate creation
Security evaluation -> temporary Store + mock source + tool boundaries
```

`ports.py` 定义来源和模型替换协议；`main.py` 组装实例。业务模块没有引用 FastAPI；`runtime.py` 是 LangGraph 适配层，`models.py` 是 LangChain 模型层。新增来源实现 `fetch`，注册到组合根，不修改差异计算。新增工具必须声明 Pydantic Schema，再通过网关统一调用。新增数据库适配保留租户作用域与唯一约束。

## 2. 核心实现

| 文件 | 责任 |
|---|---|
| app/store.py | 持久记录、租户过滤、唯一键、审计 |
| app/ingestion.py | 合成来源、Decimal 差异、哈希、配额 |
| app/service.py | 运行幂等、来源暂停、快照、建议生命周期 |
| app/memory.py | 记忆准入、工作流白名单、批准检索、撤销传播 |
| app/runtime.py | 固定图和受限工作流、节点交接、验证 |
| app/models.py | 离线模板和可选远程模型 |
| app/tools.py | MCP 工具注册及租户作用域 |
| app/evaluation.py | 六项临时环境安全测试 |
| app/main.py | HTTP、静态资源、调度、生命周期 |
| web/ | Vue 页面、样式、交互 |

采集成功后持久化观察和快照；规范哈希相同则跳过 AI。首次或前序证据撤销后建立新基线。确定性计算比较相同 SKU/币种的 Decimal 价格；缺失字段不会被视为零。当前仅模拟单件无券价格，不宣称实现真实复杂优惠叠加。

LangGraph 执行 retrieve → content → price → recommend → verify；批准的 AWM 工作流可重排 content/price，但不能删除检索、建议和复核节点。内容和价格为确定性角色节点，建议节点才可调用 LLM；这是多角色工作流，非五个自主大模型 Agent。短期上下文在 State 中，节点回执落库；长期记忆仅检索 APPROVED 且证据有效的记录。

记录表 `records` 包含 id、tenant、kind、key、payload、created，唯一约束为 tenant/kind/key。Demo 用 JSON 简化多实体迁移；生产应拆分领域表、添加外键与复合索引并使用 Alembic。当前持久化每次调用独立事务，不宣称已有 Outbox 或跨记录原子性。

## 3. Harness 与执行限制

图只允许固定节点，递归上限 12；真实模型 30 秒超时、不自动重试。节点交接必须包含结果；汇合前检查全部必需回执，缺失返回 PARTIAL 并记录故障。外部文本不进入可执行工具参数；推荐模型只收到筛选的价格差异与批准记忆。

目前未实现生产 token 计费、成本硬预算及并行分支；UI 不展示虚构 token 成本。进程重启将遗留 RUNNING 标为 INTERRUPTED，不伪装已成功；重试需新 request key。图状态记录用于审计，不是完整 LangGraph MySQL checkpointer。

Redis 在配置后执行原子固定窗口限流，所有租户共享每分钟 60 次的模拟来源配额；失败即拒绝采集。不是多维令牌桶，也不是淘宝实际配额。SQLite 模式使用内存窗口。并发由单进程 RLock 串行化，禁止开多个 uvicorn worker 或多实例。

## 4. API 与身份

`Authorization: Bearer local-demo-a` / `local-demo-b` 映射租户。默认 UI 使用两者供切换；这些是公开演示凭据，不得用于公网。若修改 DEMO_TOKEN_A/B，前端也需调整配置；生产应替换为登录会话、角色和服务身份。

| 路径 | 行为 |
|---|---|
| GET /api/state | 本租户运行、证据、建议、记忆和诊断 |
| POST /api/runs | 同步执行；支持 Idempotency-Key |
| POST /api/source/resume | 仅恢复模拟来源 |
| POST /api/recommendations/{id}/decision | 人工草稿决策，撤销证据禁止批准 |
| POST /api/recommendations/{id}/derive-workflow | 由批准建议归纳规则式 DSL 候选 |
| POST /api/memory | 提交候选，不能自动批准 |
| POST /api/memory/{id}/evaluate | DSL 与内容启发式校验 |
| POST /api/memory/{id}/review | 人工批准或停用 |
| POST /api/evidence/{id}/revoke | 先失效根证据，再停用关联记忆和建议 |
| POST /api/evaluations | 独立临时数据库运行边界测试 |
| POST /mcp | JSON-RPC initialize、tools/list、tools/call |

MCP 仅实现无状态 HTTP JSON-RPC 子集，支持三个工具：memory.search_approved、evidence.get_snapshot、memory.propose_candidate。参数不接受 tenant；批准和任意网络工具不在注册表。没有实现完整 MCP SDK、OAuth、SSE 会话或协议一致性认证。浏览器人工与 Agent 工具能力分离，但尚无生产级双人审批与角色系统。

## 5. 分层记忆和撤销

AWM 工作流是声明式操作 ID 列表；不执行模型生成代码。手动创建或从批准建议按规则归纳候选，经校验、人工批准后才检索复用。校验不等于经营有效性评测。

MemoryOS 改造：运行 State 为短期；候选经验保存在 SQL；长期记忆以 APPROVED 状态呈现。当前 tier 字段支持记录层级，但没有完整的自动中期摘要、论文 FIFO/分页晋升算法。RAG 为租户过滤后的轻量字符重合排序，不是向量检索。

MINJA 启发的治理：显式恶意指令标为 QUARANTINED；其他内容仍只进入 CANDIDATE。没有关键词也无法自动成为长期知识。批准检索每次读取根证据 active 状态，不依赖旧缓存。撤销同步停用相关记忆，并将引用该记忆/证据的建议标为 NEEDS_REVIEW；当前血缘为一层引用，生产需要全依赖链与 epoch/Outbox。

## 6. 安全评测与沙箱

网页上的评测是独立临时数据库中的确定性测试环境，不是 OS 安全沙箱。六个案例覆盖跨租户、伪造批准工具、额外租户参数、任意网络、显式与隐式记忆污染；每次同时检查正常检索仍可用。未调用攻击模型，没有完成设计要求的 60 对真实模型对抗案例。

若安装 Docker，可在构建后的镜像中执行无网络、只读文件系统、低权限的评测：

```sh
docker compose build app
docker compose run --rm --no-deps --entrypoint python app -c "from app.evaluation import evaluate_security; print(evaluate_security())"
```

上面的 compose run 只是隔离容器，不包含强化限制。使用以下独立沙箱命令启用限制（先构建独立镜像）：

```sh
docker build -t commerce-monitor-demo .
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m --cpus 1 --tmpfs /tmp:rw,noexec,nosuid,size=32m commerce-monitor-demo python -c "from app.evaluation import evaluate_security; print(evaluate_security())"
```

当前没有任意生成代码执行需求；容器命令未在本机实测。生产如执行不可信代码应使用更强隔离，不能把普通 Docker 视为充分保障。

## 7. 与企业方案的差距及扩展顺序

1. 来源接入：核验实际授权和字段，再实现官方/服务商适配器；保持合成模式明确标识。
2. 任务可靠性：异步任务表、MySQL Outbox、Redis Streams、租约与 fencing、真正 checkpoint 恢复；之后才扩容 Worker。
3. 身份：生产登录、RBAC、独立审核者、密钥系统、审计保留与删除流程。
4. 模型：质量标注集、费用统计、预算、复杂价格工具、评论聚类、向量 RAG；验证而非宣称收益。
5. 论文验收：补齐 60 对对抗场景、多次模型运行、MAST 分类复核、分层记忆消融实验。
6. 二期：AFlow 图搜索与 Mem²Evolve 新资产候选在独立模块和沙箱实现，必须先通过首期基线。

所有代码注释中的 paper 标识只表示来源机制，不表示论文算法完整实现。详见 PAPERS.md。
