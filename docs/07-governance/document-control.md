# 文档控制、责任与维护

基线`PROD-DOC-2.0`，核对日期2026-10-25，原始来源`main@e8f5503`保持不变。面向文档维护者与各职能读者，工程责任角色执行检查、相应职能角色复核，未指派个人不得伪造签署。本文为当前reference；每次合并和30天内复核。

## 1. 唯一来源与状态

项目分析记录代码事实，PRD定义FR/NFR，流程定义领域语义；架构/ADR说明方案与权衡；开发计划定义DEV任务；测试策略、追踪矩阵与验收清单连接需求和证据；运营/运维记录行为及处置；治理定义发布、风险与维护。

每个系统/流程只有一个规范定义位置；重复说明须链接规范来源或显式标成非权威历史，不能维护两份相矛盾的“当前真相”。需求ID只在PRD创建，DEV只在实施计划定义；接口以源码和data-and-api为参考，运行命令以对应how-to为准。Git/PR/CI是当前代码/合并真相，不在文本猜测SHA；验证记录只登记已观察到的命令结果。SLO/保留期/生产选型必须标待建/建议。

“已实现”必须有代码和适用范围；“部分实现”明确缺口；“目标待建”只有设计；“本次完成”是当前交付行动；“待验证”尚无运行证据；“已验收”需责任人确认且附版本/环境/日期。不得以离线模拟证明真实模型、生产性能或恢复目标。

## 2. 文档目录与维护清单

路径相对docs；README根路径单独标明。象限仅用tutorial/how-to/reference/explanation；运维或ADR另作标记。下列责任是维护路径而非已分配个人。

| Doc | Diátaxis quadrant | Responsibility path | Source of truth | Last verified | Verification cadence | Staleness signal |
|---|---|---|---|---|---|---|
| ../README.md | how-to | 工程 | 当前状态/CLI/资源 | 2026-10-25 | 每次合并 | 入口或安装命令改变 |
| README.md | reference | 工程 | 本清单/当前状态 | 2026-10-25 | 每次合并 | 规范文档遗漏 |
| 00-overview/current-state.md | reference | 工程 | 源码/验证/Git | 2026-10-25 | 合并及30天 | 行为改变未同步 |
| 00-overview/project-analysis.md | explanation | 架构/工程 | 源码/验证 | 2026-10-25 | 合并及30天 | 能力边界改变 |
| 00-overview/optimization-proposal.md | explanation | 项目 | OPT-1.0历史评估 | 2026-10-25历史标记 | 不持续重写 | 被引用为当前实施计划 |
| 01-requirements/product-requirements.md | reference | 产品 | 唯一FR/NFR目录 | 2026-10-25 | 变更/每周/合并 | 新能力无编号或旧状态 |
| 01-requirements/domain-workflows.md | explanation | 产品/工程 | 用例/状态实现 | 2026-10-25 | 变更/合并 | 状态或权限改变 |
| 01-requirements/traceability.md | reference | QA | PRD/DEV/tests | 2026-10-25 | 变更/合并 | 编号/证据不一致 |
| 02-architecture/system-design.md | explanation · architectural | 架构 | 服务/worker/存储 | 2026-10-25 | 变更/合并 | 云目标误标当前 |
| 02-architecture/data-and-api.md | reference | 后端 | DTO/HTTP/存储 | 2026-10-25 | 接口变更/合并 | 字段/状态码漂移 |
| 02-architecture/security-model.md | reference | 安全/后端 | 身份/凭据/授权实现 | 2026-10-25 | 变更/事件/合并 | 信任边界变化 |
| 02-architecture/model-and-data-governance.md | reference | 模型/数据 | 来源/配置/质量 | 2026-10-25 | 每周/变更 | 许可/目录/模型变化 |
| 02-architecture/adr/0001-modular-monolith.md | explanation · architectural | 架构 | 边界决策/源码 | 2026-10-25 | 边界变更 | 旧决策被替代 |
| 02-architecture/adr/0002-src-layout.md | explanation · architectural | 工程 | src/打包配置 | 2026-10-25 | 布局变更 | 导入/资源路径变化 |
| 02-architecture/adr/0003-research-before-execution.md | explanation · architectural | 产品/架构 | 研究域范围 | 2026-10-25 | 范围变更 | 出现真实订单需求 |
| 02-architecture/adr/0004-guided-stock-research.md | explanation · architectural | 架构/模型 | 快捷路线/预算证据 | 2026-10-25 | 路线变更/合并 | 环节/上限变化 |
| 03-development/developer-guide.md | how-to | 工程 | 工具/CI/源码 | 2026-10-25 | 命令变更/合并 | 干净安装不可用 |
| 03-development/configuration-reference.md | reference | 工程 | DEFAULT_CONFIG/DTO | 2026-10-25 | 字段变更/合并 | 无效字段/优先级漂移 |
| 03-development/directory-migration.md | reference | 工程 | 布局映射/历史 | 2026-10-25 | 路径变更 | 包路径改变 |
| 03-development/implementation-plan.md | reference | 工程/项目 | 唯一DEV目录 | 2026-10-25 | 每周/合并 | 已做事项仍待建 |
| 03-development/iteration-log.md | reference | QA | 已完成历史命令 | 2026-10-25历史标记 | 新轮追加 | 旧数字被冒充当前 |
| 03-development/managed-research.md | reference | 后端/工程 | CLI/API/管线 | 2026-10-25 | 行为变更/合并 | 参数/状态不符 |
| 03-development/research-inputs.md | reference | 前后端 | 表单/DTO/模板 | 2026-10-25 | 字段变更/合并 | 控件无来源/无作用 |
| 03-development/web-workbench.md | how-to | 产品/前端 | 实际页面/服务 | 2026-10-25 | UI变更/合并 | 入口/步骤不匹配 |
| 03-development/beginner-investor.md | explanation | 产品/QA | 上一轮历史分析 | 2026-10-25历史标记 | 不持续重写 | 旧3控件误标当前 |
| 03-development/stock-research-usability.md | explanation | 产品/模型/QA | 当前问题/实现/真实验证 | 2026-10-25 | 路线变更/合并 | 事实与金融结论混淆 |
| 04-testing/test-strategy.md | reference | QA | tests/CI/PRD | 2026-10-25 | 变更/合并 | 覆盖与实现漂移 |
| 04-testing/acceptance-checklist.md | reference | QA/产品 | 矩阵/证据/签署 | 2026-10-25 | 变更/合并 | 无证据勾选 |
| 04-testing/validation-report.md | reference | QA | 实际命令/环境/产物 | 2026-10-25 | 每轮追加 | 历史结果冒充fresh |
| 05-operations/product-operations.md | reference | 运营/产品 | 查询/账本/质量 | 2026-10-25 | 每周/事件 | 指标口径变化 |
| 06-runbooks/deployment.md | how-to · operational | SRE/工程 | CLI/CI/实例 | 2026-10-25 | 变更/30天 | 入口或版本变化 |
| 06-runbooks/observability.md | reference · operational | SRE/运营 | 查询/状态/费用 | 2026-10-25 | 事件/30天 | 指标/阈值变化 |
| 06-runbooks/incident-response.md | how-to · operational | SRE/数据/模型 | 错误/控制/恢复 | 2026-10-25 | 事件/30天 | 处置命令失效 |
| 06-runbooks/backup-recovery.md | how-to · operational | SRE/后端 | recovery/恢复测试 | 2026-10-25 | schema变更/30天 | 恢复引用或凭据规则变化 |
| 07-governance/change-release-management.md | how-to | 工程/QA | Git/PR/CI/兼容记录 | 2026-10-25 | 每次合并 | 发布/回滚步骤漂移 |
| 07-governance/document-control.md | reference | 工程/各职能 | 本清单/自动检查 | 2026-10-25 | 合并/30天 | 新文档无登记 |
| 07-governance/risk-register.md | reference | 项目/各职能 | 实现/未验边界 | 2026-10-25 | 每周/合并 | 无证据关闭风险 |

source-baseline.json记录原始拉取事实，不改原始SHA/日期；upstream/README与原上游CHANGELOG保持来源归档，非当前指导。历史提案、六轮记录和上一轮入门报告只加状态说明与当前链接，保留当时事实。

## 3. 当前状态核验与陈旧规则

本机拓扑/路由依据interfaces、application及运行端口；依赖依据锁文件；恢复依据recovery及隔离测试；生产目标只写在“待建”段。每份关键文档在周期超时、链接源码/接口/告警改变且未更新、或演练失败时标stale，并暂停作为当前操作依据；修正并验证后才能回到current。历史文档保持historical，不滚动改成新日期的运行证据。

需求/行为改变同步PRD→方案→DEV→矩阵→验收→验证→运营/运维；配置/凭据变化同步配置/安全/恢复；数据/模型变化同步质量/风险；事件复盘更新处置/观测。被替代的ADR保留理由与后继链接；误导性的重复操作说明删除或改为链接。

## 4. 文档即代码与查找验证

每个文档PR执行`python scripts/check_docs.py`：本地链接、PRD/矩阵编号及未知编号检查；CI每个PR执行同命令，失败阻断合并。`ruff`、前端构建无漂移、离线回归和包smoke验证文档所指实现。该脚本不验证远端URL、锚点、Mermaid语义或业务签署，仍需人工核验代码/状态/分母。

合并必要文档为PRD/矩阵、接口/ADR、开发/配置、测试/验收、运营、部署/事件/恢复、风险与发布。fresh验证结果进入验证记录；任何未执行的生产/金融评估保持待验。新克隆读者从README→当前状态→对应how-to即可定位启动、选股、配置、报告与处置；命令不依赖作者机器的绝对路径或私有runtime文件。
