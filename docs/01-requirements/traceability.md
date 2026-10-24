# 需求—设计—开发—测试追踪矩阵

状态：2026-10-24，六轮本地实现增量。**离线实现与校验不等于生产准入。** 开发编号定义见[实施计划](../03-development/implementation-plan.md)，逐轮命令与结果见[迭代记录](../03-development/iteration-log.md)。下列状态区分本地交付和外部待验收。

| 需求 | 设计依据 | 开发任务 | 当前证据 / 待建验收 | 状态 |
|---|---|---|---|---|
| FR-001 | [接口](../02-architecture/data-and-api.md) | DEV-010 | `test_research_mandate.py`、`test_managed_tasks.py`、`tests/system/test_managed_service.py`；字段级HTTP错误待补 | 本地输入/CLI/API已有 |
| FR-002 | [系统设计](../02-architecture/system-design.md) | DEV-020、030 | `test_managed_tasks.py`：并发幂等、领取、租约、旧attempt拒绝；外部队列/outbox另验 | 本地任务/worker已有 |
| FR-003 | [流程](domain-workflows.md) | DEV-030 | `tests/system/test_graph_end_to_end.py`、`tests/unit/test_rating_integrity.py` | 核心已有 |
| FR-004 | [数据治理](../02-architecture/model-and-data-governance.md) | DEV-070 | `test_evidence.py`及真实图消费留存/篡改检查；完整历史档案与逐论据引用待建 | 本地快照已有，known_at可为unknown |
| FR-005 | [流程](domain-workflows.md) | DEV-010、030 | `test_portfolio_context.py`、`test_research_quality.py`：有限值/去重/Decimal仓位；账户授权另验 | 固定持仓输入已有，完整估值待建 |
| FR-006 | [数据模型](../02-architecture/data-and-api.md) | DEV-050 | `test_report_lifecycle.py`、`test_evidence.py`：固定manifest/修订/复核链/hash | 本地版本已有，厂商不可变版本另验 |
| FR-007 | [数据治理](../02-architecture/model-and-data-governance.md) | DEV-090 | `test_research_evaluation.py`及system完整分母/前瞻时点/期限收益；自动网格和真实长期样本待建 | 本地计划与观察已有 |
| FR-008 | [数据模型](../02-architecture/data-and-api.md) | DEV-080 | `test_memory_pointintime.py`、真实图跨实验/attempt隔离；旧档案导入对账待建 | 托管隔离已有 |
| FR-009 | [流程](domain-workflows.md) | DEV-050 | `test_report_lifecycle.py`、`test_managed_service.py`：自审/越权/过期/硬规则/撤回 | 本地复核已有，业务签署另验 |
| FR-010 | [安全](../02-architecture/security-model.md) | DEV-040 | system本机HTTP、token撤销/到期、跨空间/scopes；OIDC/账户级权限/签名下载待建 | 本地权限已有，生产接入待建 |
| FR-011 | [治理](../02-architecture/model-and-data-governance.md) | DEV-060 | `test_managed_tasks.py`、`test_managed_service.py`：模板/任务冻结、实现变化拒绝；集中注册生效待建 | 部分已有 |
| FR-012 | [安全](../02-architecture/security-model.md) | DEV-040 | `test_report_lifecycle.py`及system访问request_id/独立audit权限；跨存储原子审计/WORM待建 | 本地追加审计已有 |
| FR-013 | [系统设计](../02-architecture/system-design.md) | DEV-060、030 | `test_managed_tasks.py`及system预算/unknown/一次性对账；厂商速率/完整成本待建 | 本地预算/deadline/取消已有 |
| FR-014 | [运营](../05-operations/product-operations.md) | DEV-110 | 待建：反馈版本关联与闭环 | 待建 |
| FR-015 | [迁移](../03-development/directory-migration.md) | DEV-001、002 | 架构测试、离线测试、仓库外wheel/CLI，[本次记录](../04-testing/validation-report.md) | 本次目录完成 |
| NFR-001 | [监控](../06-runbooks/observability.md) | DEV-100 | 待建：固定20并发1000请求压测、月SLO | 待验证 |
| NFR-002 | [系统设计](../02-architecture/system-design.md) | DEV-030、100 | `test_managed_tasks.py`：挂起/kill/超时/旧attempt/唯一接受；生产时限测量另验 | 本地故障检查已有 |
| NFR-003 | [治理](../02-architecture/model-and-data-governance.md) | DEV-060、070 | `test_evidence.py`及system实现指纹/hash；真实数据/模型不可变版本另验 | 本地可定位与完整性已有 |
| NFR-004 | [安全](../02-architecture/security-model.md) | DEV-040 | 本机权限/注入拒绝/安全错误/独立审计；TLS/加密/出口/全面安全门禁另验 | 部分已有 |
| NFR-005 | [备份恢复](../06-runbooks/backup-recovery.md) | DEV-100 | system一致快照、报告/证据/评估恢复、凭据撤销、旧attempt隔离；云RPO/RTO另验 | 本地恢复演练已有 |
| NFR-006 | [监控](../06-runbooks/observability.md) | DEV-100、060 | system完整终态分母/模型账本/unknown/暂停和冻结；集中指标/告警待建 | 本地运营查询已有 |
| NFR-007 | [测试](../04-testing/test-strategy.md) | DEV-002、100 | CI、离线回归、wheel、文档检查；真实契约/性能/恢复另验收 | 本次基础验证 |
| NFR-008 | [系统设计](../02-architecture/system-design.md) | DEV-030、100 | graph配置隔离测试局部已有；待建多进程多租户负载 | 待验证 |

表中省略路径的 `test_*.py` 在 `tests/unit/`。可执行索引与测量结果见[测试策略](../04-testing/test-strategy.md)与[验证记录](../04-testing/validation-report.md)。矩阵中的待验证不能因本次离线全套通过改为生产完成。
