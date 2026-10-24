# 数据模型与接口契约

状态：2026-10-24。本文表格为生产目标契约；已实现的本机HTTP/CLI、SQLite表与错误码见[本地手册](../03-development/managed-research.md)。适用于 FR-001、FR-002、FR-004、FR-006、FR-008、FR-009、FR-012。正式生产OpenAPI/数据库迁移治理仍待建。

本地表包括tasks/attempts/model_calls/task_events、reports/report_events、identities/access_events、controls/cost_events、experiments/predictions/observations。金额为整数micro-USD，仓位和观察收益用Decimal字符串。计划固定样本、研究契约、模板hash、显式session序列及价格口径；预测绑定已接受报告与复核事件hash，观察追加并保留来源文本/输入hash。相同session冲突拒绝，修正须另立实验。

本地路径为 `root/workspace/experiment/task/attempt`；幂等为工作空间+作者+键，HTTP成功统一200、幂等冲突400、未知对象404、跨空间403。API没有 `/api/v1` 前缀、签名下载、health、配置生效接口或自动网格调度。客户端workspace须与凭据一致，操作者由token取得；上述差异不代表生产目标已实现。

## 1. 领域实体

所有业务ID采用 UUID，UTC timestamp 精度至少毫秒；工作空间边界不得由客户端请求体覆盖。

| 实体 | 核心字段 | 唯一约束 / 不变量 |
|---|---|---|
| workspace | id、name、quota_policy_version | 身份与权限来自可信认证映射 |
| analysis_task | id、workspace_id、creator_id、request_hash、idempotency_key、status、status_version、config_version、cutoff、portfolio_version、deadline、budget | 工作空间内幂等键唯一；状态条件更新 |
| task_attempt | task_id、attempt_no、fencing_token、lease_until、worker_id、started_at、ended_at、error_code、usage | task_id + attempt_no唯一；旧 fencing 不可提交 |
| evidence_snapshot | id、workspace_id、vendor、instrument、event_time、known_at、fetched_at、content_hash、object_key、quality、license_policy、expires_at | immutable；未知 known_at 不用于严格历史任务 |
| report_version | id、task_id、version、attempt_no、rating、review_status、manifest_hash、object_key | task_id + version唯一；正文不原地修改 |
| review_event | report_id、actor_id、result、reason、created_at | 追加；审批必须验证目标版本 |
| decision_memory | workspace_id、experiment_id、task_id、ticker、analysis_date、config_hash、rating、resolved_at、outcome、reflection_version | task_id唯一；保留同ticker/date不同实验 |
| experiment / cell | config_version、snapshot_set、grid、sampling_policy；ticker、date、sample_no、task_id、status | experiment + ticker + date + sample唯一 |
| audit_event / outbox | actor、action、object、request_id、time、payload_hash；delivery_status | 追加审计；任务与outbox原子提交 |

数值价格、费用、数量在持久层使用 decimal，不以 float 做账；现有上游 portfolio float 只是研究输入，迁移 adapter 需要明确舍入规则。收益原始小数与展示百分比同时保存，避免当前文本0.1个百分点精度影响评估。

## 2. 快照与报告清单

对象路径：`workspaces/{workspace_id}/tasks/{task_id}/attempts/{attempt_no}/...`，客户端不可直接拼接路径。对象写入后保存 SHA-256、bytes、MIME、密钥版本及保留策略，发布只允许读取通过校验的引用。

报告 manifest 包含 task/attempt/report_version、ticker、市场与币种、分析日期及UTC cutoff、选定分析师、配置哈希、代码 SHA、依赖锁哈希、prompt版本、每层供应商及模型ID、供应商实际模型版本（未知则 unknown）、证据引用、结构化输出/回退状态、缺失项、usage/费用及其估算标志。不保存 API key 或带密钥的 backend_url。

单任务终态写入事务保存 report manifest 指针、评级、审计与核销预算；对象不存在或 hash 不符不可成功。遗留文件导入保留来源和原始文本，未知字段不编造，迁移不覆盖原始记录。

## 3. HTTP 接口

前缀 `/api/v1`，`Authorization: Bearer <token>`，`X-Request-ID` 可由入口生成，创建任务必须带 `Idempotency-Key`。服务从授权上下文确定 workspace_id。

| 方法 / 路径 | 行为 | 成功状态 |
|---|---|---|
| POST `/tasks` | 创建分析任务或返回幂等复用结果 | 新建202；相同请求复用200 |
| GET `/tasks/{id}` | 查询状态、有效attempt、缺失项、费用估算、报告指针 | 200 |
| POST `/tasks/{id}/cancel` | 记录取消请求，终态任务返回现有状态 | 202 或200 |
| GET `/tasks/{id}/reports` | 当前授权范围的版本列表 | 200 |
| GET `/reports/{id}` | 读取固定版本manifest与授权下载链接 | 200 |
| POST `/reports/{id}/reviews` | 以 expected_version 复核固定版本，写审计 | 201 |
| POST `/experiments` | 冻结网格及评估策略后排队 | 202 |
| GET `/experiments/{id}` | 进度、失败、pending、REVIEW、已结算指标 | 200 |
| POST `/config-versions` | 管理员提交不可变配置版本，另行审批生效 | 201 |
| GET `/health/live`、`/health/ready` | 进程存活；必要内部依赖就绪 | 200；ready未就绪503 |

示例请求，预算单位与币种固定，不由模型解释：

```json
{
  "ticker": "NVDA",
  "asset_type": "stock",
  "analysis_date": "2026-10-16",
  "analysts": ["market", "news"],
  "config_version": "cfg-uuid",
  "portfolio_version": null,
  "budget": {"currency": "USD", "max_cost": "2.00"},
  "deadline_seconds": 900
}
```

`2.00`只是契约示例，不是已批准预算。创建响应提供 task_id、status、status_url、request_id；错误统一为 `{code, message, request_id, details}`，details仅包含安全的字段错误。

## 4. 错误与并发

400/422：输入/日期/配置不合法；401：认证失败；404：不存在或调用者不可见，避免泄露租户对象；403：在可见对象上操作权限不足；409：幂等键内容不同、版本冲突或非法状态转换；429：配额不足，给出 Retry-After；503：必要内部服务不可用。

分页使用游标、默认50/最大200，排序键含ID以避免相同时间漏项。写操作带 expected_version，更新零行即冲突。网络超时后客户端使用同一幂等键重试，禁止自动换键。

ready 检查数据库/队列等内部依赖，外部模型波动记录指标，不使所有 API 实例一起退出就绪。任何 endpoint、ticker、文件路径和报告 HTML 均按[安全设计](security-model.md)验证。
