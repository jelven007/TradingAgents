# 项目分析：能力、架构与生产差距

状态：2026-10-25当前实现分析，来源基线仍为2026-10-23的`main@e8f5503`，包版本0.7.0表示上游来源。工程责任角色依据源码、[验证记录](../04-testing/validation-report.md)和[股票改进](../03-development/stock-research-usability.md)维护，每次能力或发布变化复核；面向产品/架构/工程。已做真实NVDA单样本，不进行投资效果背书。

## 1. 定位与技术组成

项目是 Python 多智能体金融研究框架。LangGraph 组织状态与节点，LangChain 连接模型及工具，Pydantic 约束结构化输出；Typer、Rich、Questionary 提供 CLI；Pandas、Stockstats 处理行情；Requests、yfinance 访问外部数据；SQLite 与 Markdown 文件持久化状态。

当前核心价值是降低选股到可解释判断的工作量：内置目录、推荐值、预算内有界研究、支持/反方/风险与固定证据。已有本机服务、密码账号、模型设置、工作台、复核、个人关注与评估；生产组织身份、云存储/队列、许可、长期质量与SLO仍需建设。没有胜率或收益优于市场的证据。

## 2. 当前默认与专业运行链路

默认工作台：选择股票/问题→真实行情、公司、新闻、基准与FX→资料分析→多方→反方→风险综合→固定报告与质量→待复核。最多8次模型调用；真实4次收尾。资料不足返回Insufficient而不默认Hold。下面保留显式专业完整图，其SDK/CLI行为兼容。

```mermaid
flowchart TD
  I["股票代码、日期、配置、可选持仓"] --> A["行情 / 情绪 / 新闻 / 基本面分析师并行"]
  I --> M["历史决策结算与记忆并行"]
  A --> B["多空研究辩论"]
  M --> B
  B --> R["研究经理"]
  R --> T["Trader 建议"]
  T --> K["激进 / 中性 / 保守风险辩论"]
  K --> P["组合经理：五档评级或 REVIEW"]
  P --> O["报告、决策日志、回测评估"]
```

所有选定分析师和记忆节点结束后才进入研究辩论，组合经理消费历史经验。并行化不会把分析师工具消息混入其他分析师上下文。决策评级不是订单；`REVIEW` 也不是 `Hold`。

## 3. 能力与代码证据

| 能力 | 当前情况 | 实现证据 |
|---|---|---|
| CLI、SDK | 已实现交互及无交互分析、回测、登录命令 | [CLI](../../src/cli/main.py)、[分析图](../../src/tradingagents/graph/trading_graph.py) |
| 智能体编排 | 四类分析师并行，多空及风险辩论，深浅模型分层 | [图构建](../../src/tradingagents/graph/setup.py)、[分析计划](../../src/tradingagents/graph/analyst_execution.py) |
| 结构化建议 | 研究计划、交易建议、组合决策、情绪报告 schema | [输出模型](../../src/tradingagents/agents/schemas.py)、[评级解析](../../src/tradingagents/agents/rating.py) |
| 数据访问 | 显式供应商链、工具级覆盖、分类错误与不可用提示 | [数据路由](../../src/tradingagents/dataflows/router.py)、[错误](../../src/tradingagents/dataflows/errors.py) |
| 时点处理 | 日期边界、SEC filed 时间、历史记忆可知时间等已有保护 | [日期窗口](../../src/tradingagents/dataflows/date_window.py)、[SEC](../../src/tradingagents/dataflows/vendors/sec_edgar.py) |
| 外部数据 | Yahoo、Alpha Vantage、SEC、FRED、Polymarket、Reddit、Stocktwits；各来源覆盖不同 | [供应商](../../src/tradingagents/dataflows/vendors/) |
| 模型接入 | 多家供应商、兼容端点、本地模型，深浅层可分别配置 | [工厂](../../src/tradingagents/llm_clients/factory.py)、[模型能力](../../src/tradingagents/llm_clients/capabilities.py) |
| 报告 | 分节 Markdown、整合 Markdown/HTML、配置摘要 | [报告写入](../../src/tradingagents/reporting.py)、[HTML](../../src/tradingagents/report_html.py) |
| 记忆与恢复 | 文件锁、决策去重、历史结算、可选 SQLite checkpoint | [记忆](../../src/tradingagents/memory/log.py)、[checkpoint](../../src/tradingagents/graph/checkpointer.py) |
| 决策回测 | ticker × date 网格、独立日志、断点继续、按评级算超额收益 | [回测](../../src/tradingagents/backtest.py)、[结算](../../src/tradingagents/memory/settlement.py) |
| 工程保障 | 离线默认测试、供应商模拟、CI、wheel 发布、非 root 容器 | [测试](../../tests/)、[CI](../../.github/workflows/ci.yml) |
| 股票默认流程 | 21,271条目录、原币种/推荐基准、USD/CNY显示、有界真实研究 | [快捷研究](../../src/tradingagents/application/guided_stock.py)、[目录](../../src/tradingagents/application/securities.py) |
| 本机产品闭环 | 密码/CSRF、版本化模型/模板、指定执行、自动报告、复核、关注与笔记 | [服务](../../src/tradingagents/application/service.py)、[工作台](../../web/src/main.jsx) |

## 4. 关键语义与限制

- 数据日期与可知日期不同。历史财务数据需在分析日之前披露；非美国 Yahoo 报表缺乏披露时间，因此历史运行会拒绝相关数据。历史持有人交易、无时点快照的工具也有各自限制。
- 回测入场基准是分析日期之后的第一个收盘价，持有窗口按交易日计；基准跨市场按区域映射与日期对齐。现有 alpha 取自文本百分比，精度约为 0.1 个百分点。
- 回测各单元独立，可选 portfolio 在网格中保持不变；没有资金流水、滑点、手续费、调仓或真实成交建模。
- 文件记忆当前按 ticker + date 去重。相同日期的不同模型实验若共用文件会互相抑制，生产设计必须引入实验、租户与配置隔离。
- SQLite checkpoint 和文件锁适合单机受控运行。文件锁不等于跨集群一致性；同一 `TradingAgentsGraph` 实例有可变 checkpoint 状态，不应并发共享。
- 报告记录模型与供应商配置，但新闻/社交原始内容尚未完整归档。历史边界保护无法保证重新抓取的数据集与第一次完全相同；模型输出本身也不保证确定性。
- 原始 README 描述了“送往模拟交易所执行”，但仓库没有订单、资金账本或 broker adapter。生产需求必须纠正这个能力边界。

## 5. 面向生产的差距优先级

| 优先级 | 缺口 | 后果 | 建设方向 |
|---|---|---|---|
| P0 | 公司身份、账户级授权、集群隔离缺失；本机scope/幂等/审计已有 | 生产部署不能直接复用本机边界 | OIDC、集中授权与集群验收 |
| P0 | 原始证据快照与可知时间治理不完整 | 不能证明决策输入、不能稳定重放 | 不可变快照与版本清单 |
| P0 | 本机预算/超时/账本已有，价格表、厂商配额、集中监控待建 | 预留不等于账单，缺少生产告警 | 费用对账、供应商配额与指标 |
| P1 | 集中存储、恢复、持续评估缺失 | 多副本一致性和发布风险 | PostgreSQL、对象存储、评估门禁 |
| P1 | 工作台/复核已有，正式反馈平台与真实长期评估待建 | 缺少组织质量运营闭环 | 反馈版本关联和代表性评估 |
| 后续立项 | 成交与资金系统不存在 | 不能由研究评级直接执行交易 | 独立订单域及确定性风控 |

生产目标与验收见[需求](../01-requirements/product-requirements.md)，方案见[系统设计](../02-architecture/system-design.md)。
