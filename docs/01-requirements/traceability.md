# 需求—设计—开发—测试追踪矩阵

状态：2026-10-25，`PROD-DOC-2.0`；面向工程/QA，QA责任角色维护，每次需求/测试变化和合并前核对。**本机工程与真实单样本不等于生产准入或金融有效性。** 需求编号唯一来源为[PRD](product-requirements.md)，开发编号为[实施计划](../03-development/implementation-plan.md)，历史及本次证据在[验证记录](../04-testing/validation-report.md)。

浏览器增量覆盖FR-001/FR-002/FR-006/FR-007/FR-009/FR-010/FR-012/FR-013的本地交互入口：任务、报告复核、评估和运营页面，详见[Web工作台](../03-development/web-workbench.md)。`tests/system/test_web_workbench.py`验证同源HTTP、会话、分页/范围和指定任务执行；桌面/手机及fixture复核/观察/对账的浏览器证据见[验证记录](../04-testing/validation-report.md)。公司身份与生产依赖仍保留表中待验收。

模型设置增量覆盖FR-011及FR-010/NFR-004/NFR-005的本地配置、凭据和恢复入口。`tests/system/test_model_settings.py`验证加密存储、按层隔离、版本冲突、旧任务固定、权限和错误脱敏、连接上限与恢复后新密钥；浏览器验证保存/保留/清除/重连。该实现不替代厂商不可变模型版本、云secret manager、审批生效或完整生产出口验收。

账号入口增量覆盖FR-010/NFR-004/NFR-005：本机首次管理员创建、账号密码登录、HttpOnly会话/CSRF、角色导航、账号管理和恢复撤销会话，证据为`tests/system/test_browser_login.py`及[浏览器记录](../04-testing/validation-report.md)。从首页到任务/报告/评估/运营/模型配置逐页可用，生产组织认证和账户级持仓授权仍另验。

| 需求 | 设计依据 | 开发任务 | 当前证据 / 待建验收 | 状态 |
|---|---|---|---|---|
| FR-001 | [接口](../02-architecture/data-and-api.md) | DEV-010、130 | `test_research_mandate.py`、`test_managed_tasks.py`、`tests/system/test_research_inputs.py`；实际字段/焦点/草稿两轮 | 本机字段级错误已有 |
| FR-002 | [系统设计](../02-architecture/system-design.md) | DEV-020、030 | `test_managed_tasks.py`：并发幂等、领取、租约、旧attempt拒绝；外部队列/outbox另验 | 本地任务/worker已有 |
| FR-003 | [流程](domain-workflows.md) | DEV-030、140 | `test_graph_end_to_end.py`、`test_rating_integrity.py`、`test_guided_stock.py`；真实4次快捷调用 | 完整/快捷路线已有 |
| FR-004 | [数据治理](../02-architecture/model-and-data-governance.md) | DEV-070 | `test_evidence.py`及真实图消费留存/篡改检查；完整历史档案与逐论据引用待建 | 本地快照已有，known_at可为unknown |
| FR-005 | [流程](domain-workflows.md) | DEV-010、030 | `test_portfolio_context.py`、`test_research_quality.py`：有限值/去重/Decimal仓位；账户授权另验 | 固定持仓输入已有，完整估值待建 |
| FR-006 | [数据模型](../02-architecture/data-and-api.md) | DEV-050 | `test_report_lifecycle.py`、`test_evidence.py`：固定manifest/修订/复核链/hash | 本地版本已有，厂商不可变版本另验 |
| FR-007 | [数据治理](../02-architecture/model-and-data-governance.md) | DEV-090 | `test_research_evaluation.py`及system完整分母/前瞻时点/期限收益；自动网格和真实长期样本待建 | 本地计划与观察已有 |
| FR-008 | [数据模型](../02-architecture/data-and-api.md) | DEV-080 | `test_memory_pointintime.py`、真实图跨实验/attempt隔离；旧档案导入对账待建 | 托管隔离已有 |
| FR-009 | [流程](domain-workflows.md) | DEV-050 | `test_report_lifecycle.py`、`test_managed_service.py`：自审/越权/过期/硬规则/撤回 | 本地复核已有，业务签署另验 |
| FR-010 | [安全](../02-architecture/security-model.md) | DEV-040、120 | `test_browser_login.py`及本机HTTP、token撤销、CSRF、跨空间/scopes；OIDC/账户授权待建 | 本机密码/权限已有 |
| FR-011 | [治理](../02-architecture/model-and-data-governance.md) | DEV-060 | `test_managed_tasks.py`、`test_managed_service.py`、`tests/system/test_model_settings.py`：模板/任务冻结、模型设置版本与密钥隔离、实现变化拒绝；生产审批注册待建 | 本地模型设置已有，生产治理另验 |
| FR-012 | [安全](../02-architecture/security-model.md) | DEV-040 | `test_report_lifecycle.py`及system访问request_id/独立audit权限；跨存储原子审计/WORM待建 | 本地追加审计已有 |
| FR-013 | [系统设计](../02-architecture/system-design.md) | DEV-060、030 | `test_managed_tasks.py`及system预算/unknown/一次性对账；厂商速率/完整成本待建 | 本地预算/deadline/取消已有 |
| FR-014 | [运营](../05-operations/product-operations.md) | DEV-110 | 待建：反馈版本关联与闭环 | 待建 |
| FR-015 | [迁移](../03-development/directory-migration.md) | DEV-001、002 | 架构测试、离线测试、仓库外wheel/CLI，[本次记录](../04-testing/validation-report.md) | 本次目录完成 |
| FR-016 | [股票契约](../03-development/stock-research-usability.md) | DEV-140 | `test_guided_stock.py`：21,271条、名称/市场/分页/权限、打包目录；三屏实操 | 本机已验证 |
| FR-017 | [数据接口](../02-architecture/data-and-api.md) | DEV-140、150 | 目录原币种/基准、USD/CNY、有效汇率；真实报告210.96 USD及1405.12 CNY | 本机已验证 |
| FR-018 | [股票契约](../03-development/stock-research-usability.md) | DEV-140 | 8次门禁、调用账本、网络/解析/截断/异常行情；真实4次收尾 | 本机已验证 |
| FR-019 | [工作台](../03-development/web-workbench.md) | DEV-150 | 原文/缺项/质量/损坏拒读；真实报告桌面/手机理由、风险、条件 | 本机已验证 |
| FR-020 | [流程](domain-workflows.md) | DEV-150 | `test_beginner_investor.py`；关注并发/本人隔离/重启/失败恢复实操 | 本机已验证 |
| FR-021 | [字段契约](../03-development/research-inputs.md) | DEV-120、130 | `test_model_settings.py`、`test_research_inputs.py`、两轮字段配置与三屏创建 | 本机已验证 |
| NFR-001 | [监控](../06-runbooks/observability.md) | DEV-100 | 待建：固定20并发1000请求压测、月SLO | 待验证 |
| NFR-002 | [系统设计](../02-architecture/system-design.md) | DEV-030、100 | `test_managed_tasks.py`：挂起/kill/超时/旧attempt/唯一接受；生产时限测量另验 | 本地故障检查已有 |
| NFR-003 | [治理](../02-architecture/model-and-data-governance.md) | DEV-060、070 | `test_evidence.py`及system实现指纹/hash；真实数据/模型不可变版本另验 | 本地可定位与完整性已有 |
| NFR-004 | [安全](../02-architecture/security-model.md) | DEV-040 | 本机权限/注入拒绝/安全错误/独立审计；TLS/加密/出口/全面安全门禁另验 | 部分已有 |
| NFR-005 | [备份恢复](../06-runbooks/backup-recovery.md) | DEV-100 | system一致快照、报告/证据/评估恢复、凭据撤销、旧attempt隔离；云RPO/RTO另验 | 本地恢复演练已有 |
| NFR-006 | [监控](../06-runbooks/observability.md) | DEV-100、060 | system完整终态分母/模型账本/unknown/暂停和冻结；集中指标/告警待建 | 本地运营查询已有 |
| NFR-007 | [测试](../04-testing/test-strategy.md) | DEV-002、100 | CI、离线回归、wheel、文档检查；真实契约/性能/恢复另验收 | 本次基础验证 |
| NFR-008 | [系统设计](../02-architecture/system-design.md) | DEV-030、100 | graph配置隔离测试局部已有；待建多进程多租户负载 | 待验证 |
| NFR-009 | [工作台](../03-development/web-workbench.md) | DEV-130、150 | 桌面1440×1000、手机390×844、横屏844×390实际控件全链路；无pageerror/溢出 | 本机已验证 |
| NFR-010 | [股票契约](../03-development/stock-research-usability.md) | DEV-140 | `test_guided_stock.py`：8次上限、缺口、预算异常传播、异常价格不调用模型 | 本机已验证 |

测试路径以`tests/unit/`、`tests/system/`为准；新增`test_guided_stock.py`、`test_browser_login.py`、`test_beginner_investor.py`、`test_model_settings.py`和`test_research_inputs.py`均在system。矩阵的生产待验证不因离线测试通过改为完成。文档全链条更新及推送/合并属于DEV-160，结果由本次验证记录和仓库状态证明。
