# 文档导航与阅读路径

文档基线 `PROD-DOC-1.0`，日期 2026-10-23，代码来源 `e8f5503`。这是基于代码事实形成的**待业务评审设计基线**；需求、预算、SLO、保留期和排期均为建议，尚未获得业务批准。目录迁移已执行，生产平台功能的实施状态以追踪矩阵为准。

2026-10-24新增[金融研究生产化优化建议书](00-overview/optimization-proposal.md)，基于本地提交 `9dd5b06`，从业务流程、技术、开发、测试、运营和运维六个维度提出优先级调整、12项优化建议与90天行动路线。该建议书为待评审增量，未将建议自动改为正式需求或已实现能力。

经用户授权的增量实现与验证见[逐轮迭代记录](03-development/iteration-log.md)，当前可用接口见[托管研究本地运行](03-development/managed-research.md)。本地能力与外部生产验收分开记录。

## 按职责阅读

| 对象 | 推荐材料 | 要解决的问题 |
|---|---|---|
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
- [原始上游说明](upstream/README.md)是历史来源，生产设计中的能力判断以代码分析为准。

## 文档协作规则

所有需求使用 `FR-NNN` 或 `NFR-NNN`，开发任务使用 `DEV-NNN`，验收项使用 `AC-NNN`，风险使用 `RISK-NNN`。文档必须说明“已实现”“部分实现”“目标待建”或“本次已完成”，不可仅凭目录存在宣称功能实现。

需求目录是需求编号的唯一来源，矩阵必须覆盖全部需求。根目录运行 `python scripts/check_docs.py` 校验本地 Markdown 文件链接和需求编号；该检查不代替业务评审，也不校验 Mermaid 语义、锚点或远端链接。
