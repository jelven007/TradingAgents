# 文档导航与阅读路径

文档基线`PROD-DOC-2.0`，核对日期2026-10-25，原始代码来源e8f5503。面向各职能读者，工程责任角色每次合并前维护导航；[当前状态](00-overview/current-state.md)汇总已实现事实，[文档控制](07-governance/document-control.md)登记全部文档责任/来源/周期/陈旧信号。本机功能已有验证；生产SLO、保留期、云选型与业务批准仍待完成。

历史[金融研究生产化优化建议书](00-overview/optimization-proposal.md)基于2026-10-24的9dd5b06，保留当时建议，非当前实施状态；后续能力以当前状态、PRD、矩阵和验证记录为准，不把建议自动视为已建。

经用户授权的增量实现与验证见[逐轮迭代记录](03-development/iteration-log.md)，当前可用接口见[托管研究本地运行](03-development/managed-research.md)。本地能力与外部生产验收分开记录。

新增[浏览器研究工作台](03-development/web-workbench.md)：同一本机服务提供中文交互页面，包含任务、报告复核、评估和运营入口；当前访问`http://127.0.0.1:8783/`，使用已有密码账号或体验隔离演示。

2026-10-25完成[入门投资者改进](03-development/beginner-investor.md)，随后完成[股票研究易用性与真实执行](03-development/stock-research-usability.md)：21,271条内置证券资料、买入/持有/卖出问题、推荐基准、独立显示币种和预算内收尾；真实NVDA已用4次模型调用生成草稿。完整参数、复核、关注与笔记继续可用，实际验证见[验收记录](04-testing/validation-report.md)。

## 按职责阅读

| 对象 | 推荐材料 | 要解决的问题 |
|---|---|---|
| 首次使用的投资者 | [股票研究与结果](03-development/stock-research-usability.md)、[工作台手册](03-development/web-workbench.md) | 选股票、看判断依据和风险、保存关注及笔记 |
| 所有参与者 | [项目分析](00-overview/project-analysis.md) | 系统已有能力与局限 |
| 产品、业务 | [产品需求](01-requirements/product-requirements.md)、[业务流程](01-requirements/domain-workflows.md) | 服务对象、边界、验收 |
| 架构、技术负责人 | [系统设计](02-architecture/system-design.md)、[数据与接口](02-architecture/data-and-api.md) | 技术边界、一致性、扩展 |
| 安全与模型负责人 | [安全设计](02-architecture/security-model.md)、[模型及数据治理](02-architecture/model-and-data-governance.md) | 权限、证据、变更风险 |
| 开发 | [开发指南](03-development/developer-guide.md)、[配置](03-development/configuration-reference.md)、[目录迁移](03-development/directory-migration.md) | 本地开发与依赖边界 |
| 项目负责人 | [实施计划](03-development/implementation-plan.md)、[追踪矩阵](01-requirements/traceability.md) | 依赖、进度和交付门禁 |
| QA | [测试策略](04-testing/test-strategy.md)、[验收清单](04-testing/acceptance-checklist.md)、[验证记录](04-testing/validation-report.md) | 覆盖、证据、发布条件 |
| 运营 | [运营方案](05-operations/product-operations.md) | 使用、质量、反馈、成本 |
| 运维、SRE | [部署](06-runbooks/deployment.md)、[监控](06-runbooks/observability.md)、[故障](06-runbooks/incident-response.md)、[恢复](06-runbooks/backup-recovery.md) | 服务保障及恢复 |
| 治理、管理 | [变更发布](07-governance/change-release-management.md)、[风险](07-governance/risk-register.md)、[文档控制](07-governance/document-control.md) | 责任、审批和持续维护 |

## 来源与设计决策

- [来源记录](00-overview/source-baseline.json)：远端、分支、完整 SHA、版本、许可证、拉取方式。
- [ADR-0001](02-architecture/adr/0001-modular-monolith.md)：采用模块化单体和独立进程 worker。
- [ADR-0002](02-architecture/adr/0002-src-layout.md)：采用 `src/` 布局，保留现有 Python 导入。
- [ADR-0003](02-architecture/adr/0003-research-before-execution.md)：先建设研究平台，订单执行独立立项。
- [ADR-0004](02-architecture/adr/0004-guided-stock-research.md)：默认股票研究采用固定有界路线，保留专业完整图。
- [原始上游说明](upstream/README.md)是历史来源，生产设计中的能力判断以代码分析为准。
- [新建研究输入](03-development/research-inputs.md)：字段来源、可操作模板、持仓与估值、错误恢复及逐项验收。

## 文档协作规则

所有需求使用 `FR-NNN` 或 `NFR-NNN`，开发任务使用 `DEV-NNN`，验收项使用 `AC-NNN`，风险使用 `RISK-NNN`。文档必须说明“已实现”“部分实现”“目标待建”或“本次已完成”，不可仅凭目录存在宣称功能实现。

需求目录是需求编号的唯一来源，矩阵必须覆盖全部需求。根目录运行 `python scripts/check_docs.py` 校验本地 Markdown 文件链接和需求编号；该检查不代替业务评审，也不校验 Mermaid 语义、锚点或远端链接。
