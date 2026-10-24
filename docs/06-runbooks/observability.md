# 观测、SLO、告警与容量

状态：2026-10-24，已有本地task/attempt/call账本、request_id访问审计、完整终态/复核/费用查询和控制开关，见[本地手册](../03-development/managed-research.md)。以下Prometheus/Trace、集中指标/告警仍为目标；NFR-001/NFR-006的SLO待部署测量与负责人确认。

本地 `operations`与`audit`使用独立scope；账单未知单列，不用预留额冒充已付费用。`control pause_submissions`暂停新准入，`control freeze_publication`阻止报告发布，既有幂等任务可查询；两者不自动取消正在运行的模型调用。默认deadline1800秒，与下文15分钟生产建议区分。尚未完成20并发1000请求压测、集中时序指标、自动告警或月可用性测量。

## 1. 关联与指标

日志字段：timestamp、severity、service、code_version、request_id、task_id、attempt_no、workspace匿名ID、node、provider、duration、result、error_code。持仓、原始prompt、密钥、完整backend URL不进入日志。Trace串联入口→任务→节点→工具/模型→报告，但正文采样需单独授权。

建议Prometheus/OpenTelemetry兼容指标：

| 指标 | 维度与口径 |
|---|---|
| api_requests_total / duration_seconds | route模板、status、service；不按task/ticker作label |
| task_terminal_total / task_duration_seconds | outcome、asset_type、模型配置组 |
| queue_oldest_age_seconds / backlog | 队列、任务类型 |
| worker_active / lease_expired_total / duplicate_rejected_total | worker池和任务类型 |
| provider_calls_total / duration / retries_total | provider、operation、result |
| data_unavailable_total / stale_data_total | vendor、工具类别、市场 |
| llm_tokens_total / estimated_cost_total / unknown_usage_total | provider、模型价格版本；未知费用不计0 |
| report_review_total / evidence_missing_total | REVIEW/复核结果、缺失类别 |
| storage_errors_total / backup_age_seconds | 组件、备份类型 |

task_id、用户、ticker等高基数字段只放日志/trace，不做metric label。成本支持账单对账后的修正事件，禁止反向改写原始usage。

## 2. SLO与告警建议

控制面月可用≥99.5%，排除错误输入/权限拒绝，服务器5xx和无法提交任务计不可用；p95≤500ms采用固定压测口径。研究任务耗时另计，默认15分钟deadline，超过60秒仍无终态视为恢复异常。

| 条件 | 建议级别 | 初始动作 |
|---|---|---|
| 控制面5xx>5%持续5分钟 | SEV1 | 查内部DB/队列，停止扩大发布 |
| 最老排队任务>5分钟持续10分钟 | SEV2 | 查worker/供应商配额，不直接无限扩容 |
| provider失败>20%且样本≥20，持续10分钟 | SEV2 | 查限额/网络/模型退役，冻结链内降级 |
| 任一时点泄漏或跨租户访问成功 | SEV1 | 暂停相关报告发布，保留证据 |
| 费用达到月预算80% / 100% | 提醒 / 阻断新增任务 | 对账unknown及重试，按业务策略执行 |
| 备份年龄>24小时试运行 / >15分钟生产PITR | SEV2 | 验证备份流水，不仅检查进程存活 |
| 磁盘/对象配额使用>80% / >90% | 提醒 / SEV2 | 查增长与保留策略，保护审计/记忆 |

阈值是初始建议，需要消噪/负载验证；恢复通知与告警去重应按同一事件关联。外部供应商故障不使所有API readiness同时失败。

## 3. 容量与值班

从worker并发2、每进程单任务开始，内部分析师并行算入供应商调用总数；按tokens/min、requests/min、p95内存、数据速率、DB池和队列延迟设上限。扩大并发前完成NFR-008隔离与压测，不以低CPU认定可以无限加任务。

日报查看任务终态、失败来源、backlog、费用unknown、REVIEW、缺失与备份；周报分析版本趋势和SLO；变更后观察与相同基线比较。值班负责确认、止损和关联技术负责人，事后由责任方补根因与回归证据，见[故障响应](incident-response.md)。
