# 最新论文技术：来源、采用方式和实现边界

研究窗口：2024-10-23 至 2026-10-23；按正式发表时间。沿用已确认方案中核对的官方论文来源。本 Demo 不引用论文基准提升作为淘宝运营收益。

| 决策 | 来源论文 | 代码与演示 | 未实现部分 |
|---|---|---|---|
| 首期① | [Agent Workflow Memory，ICML 2025](https://proceedings.mlr.press/v267/wang25bx.html) | main.derive 归纳批准轨迹；memory 的 DSL 审核；runtime.invoke 重排批准步骤 | 原论文 LLM 自主工作流归纳、网页导航基准复现 |
| 首期③ | [Memory OS of AI Agent，EMNLP 2025](https://aclanthology.org/2025.emnlp-main.1318/) | GraphState 短期状态、SQL 经验候选、批准长期记忆与检索 | 完整中期自动摘要、FIFO 和分段分页晋升 |
| 首期④ | [Why Do Multi-Agent LLM Systems Fail?，NeurIPS 2025](https://neurips.cc/virtual/2025/poster/121528) | runtime.receipt/verify 检查交接与错误完成；failure 记录 | MAST 全部细类自动标注与多模型标注一致性 |
| 首期⑤ | [AgentDojo，NeurIPS 2024 Datasets and Benchmarks Track](https://proceedings.neurips.cc/paper_files/paper/2024/hash/97091a5177d8dc64b1da8bf3e1f6fb54-Abstract-Datasets_and_Benchmarks_Track.html) | evaluation.py 的独立环境与正常/攻击边界检查 | 原基准环境、真实模型适应性攻击、60 对电商样本 |
| 首期⑥ | [Memory Injection Attacks on LLM Agents via Query-Only Interaction，NeurIPS 2025](https://proceedings.neurips.cc/paper_files/paper/2025/hash/42a97bbd9844d2bf68596730af80bcdf-Abstract-Conference.html) | memory.propose/approved/revoke；工具层无批准能力；污染候选跨运行不可检索 | MINJA 攻击生成复现、完整依赖图撤销 |
| 二期② | [AFlow，ICLR 2025](https://proceedings.iclr.cc/paper_files/paper/2025/hash/5492ecbce4439401798dcd2c90be94cd-Abstract-Conference.html) | 尚未实现；预留 runtime 工作流接口 | 自动图搜索、MCTS、成本与质量优化 |
| 二期⑦ | [Mem²Evolve，ACL 2026](https://aclanthology.org/2026.acl-long.952/) | 尚未实现；经验记录与 Skill 候选可作为后续接口 | 经验/资产共同迭代及新能力生成 |

⑧ A-Mem 暂不采用。记忆到证据的简单引用只用于溯源和撤销，不属于语义记忆关联图。

## 论文机制与工程新增的区分

- AWM 启发流程复用；工具白名单、人工批准、版本与权限限制是企业场景改造。
- MemoryOS 启发分层记忆；租户过滤、证据有效性优先与审批规则是项目设计。
- MAST 是失败分析框架，不提供“永不失败”的调度器；本 Demo 的规则检测只覆盖一小部分故障。
- AgentDojo 提供评测范式；本项目独立构造六项工具边界案例，没有直接运行其完整基准。
- MINJA 是攻击研究；本项目从其威胁模型推导记忆准入与撤销防护，不能声称这些措施已被原论文证明充分。

首期 RSI 演示为：批准建议 → 规则式提炼候选 → 校验 → 人工批准 → 下一轮复用 → 停用。它不是自主递归改进模型，也不会自动生成生产工具。
