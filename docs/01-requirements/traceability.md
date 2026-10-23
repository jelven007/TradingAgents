# 需求—设计—开发—测试追踪矩阵

状态：2026-10-23。**已有核心覆盖不等于平台需求完成。** “待建用例”没有测试文件，必须在实施PR补充；已有文件只证明所述局部能力。开发编号定义见[实施计划](../03-development/implementation-plan.md)。

| 需求 | 设计依据 | 开发任务 | 当前证据 / 待建验收 | 状态 |
|---|---|---|---|---|
| FR-001 | [接口](../02-architecture/data-and-api.md) | DEV-010 | `tests/unit/test_date_boundaries.py`、`test_symbols.py`；待建API校验 | 核心部分已有 |
| FR-002 | [系统设计](../02-architecture/system-design.md) | DEV-020、030 | 待建：同键重试/异键冲突/重复投递/租约/fencing | 待建 |
| FR-003 | [流程](domain-workflows.md) | DEV-030 | `tests/system/test_graph_end_to_end.py`、`tests/unit/test_rating_integrity.py` | 核心已有 |
| FR-004 | [数据治理](../02-architecture/model-and-data-governance.md) | DEV-070 | `test_statement_knowledge_time.py`、`test_news_lookahead.py`等；待建快照重放 | 部分已有 |
| FR-005 | [流程](domain-workflows.md) | DEV-010、030 | `tests/unit/test_portfolio_context.py`；待建持仓版本/授权 | 部分已有 |
| FR-006 | [数据模型](../02-architecture/data-and-api.md) | DEV-050 | `tests/unit/test_reporting.py`、`test_report_html.py`；待建manifest/版本 | 部分已有 |
| FR-007 | [数据治理](../02-architecture/model-and-data-governance.md) | DEV-090 | `tests/system/test_backtest.py`；待建实验调度和统计服务 | 核心已有 |
| FR-008 | [数据模型](../02-architecture/data-and-api.md) | DEV-080 | `tests/unit/test_memory_pointintime.py`；待建跨实验/工作空间隔离 | 部分已有 |
| FR-009 | [流程](domain-workflows.md) | DEV-050 | 待建：固定版本复核/审批/撤回/REVIEW拦截 | 待建 |
| FR-010 | [安全](../02-architecture/security-model.md) | DEV-040 | 待建：认证、全对象跨租户、签名链接授权 | 待建 |
| FR-011 | [治理](../02-architecture/model-and-data-governance.md) | DEV-060 | `tests/unit/test_cli_config_precedence.py`；待建不可变注册/生效/回滚 | 部分已有 |
| FR-012 | [安全](../02-architecture/security-model.md) | DEV-040 | 待建：操作审计完整性和权限 | 待建 |
| FR-013 | [系统设计](../02-architecture/system-design.md) | DEV-060、030 | `test_llm_max_retries.py`、`test_llm_max_tokens.py`；待建总预算/取消 | 部分已有 |
| FR-014 | [运营](../05-operations/product-operations.md) | DEV-110 | 待建：反馈版本关联与闭环 | 待建 |
| FR-015 | [迁移](../03-development/directory-migration.md) | DEV-001、002 | 架构测试、离线测试、仓库外wheel/CLI，[本次记录](../04-testing/validation-report.md) | 本次目录完成 |
| NFR-001 | [监控](../06-runbooks/observability.md) | DEV-100 | 待建：固定20并发1000请求压测、月SLO | 待验证 |
| NFR-002 | [系统设计](../02-architecture/system-design.md) | DEV-030、100 | `tests/system/test_checkpoint_resume.py`；待建kill/超时/重复接收 | 部分已有 |
| NFR-003 | [治理](../02-architecture/model-and-data-governance.md) | DEV-060、070 | 待建：版本清单完整性/冻结输入重放 | 待建 |
| NFR-004 | [安全](../02-architecture/security-model.md) | DEV-040 | 路径和scrub测试局部已有；待建租户/SSRF/secret/审计门禁 | 部分已有 |
| NFR-005 | [备份恢复](../06-runbooks/backup-recovery.md) | DEV-100 | 待建：带时间戳的备份与恢复演练 | 待验证 |
| NFR-006 | [监控](../06-runbooks/observability.md) | DEV-100、060 | CLI统计局部已有；待建服务指标/告警/未知费用 | 待建 |
| NFR-007 | [测试](../04-testing/test-strategy.md) | DEV-002、100 | CI、离线回归、wheel、文档检查；真实契约/性能/恢复另验收 | 本次基础验证 |
| NFR-008 | [系统设计](../02-architecture/system-design.md) | DEV-030、100 | graph配置隔离测试局部已有；待建多进程多租户负载 | 待验证 |

表中省略路径的 `test_*.py` 在 `tests/unit/`。可执行索引与测量结果见[测试策略](../04-testing/test-strategy.md)与[验证记录](../04-testing/validation-report.md)。矩阵中的待验证不能因本次离线全套通过改为生产完成。
