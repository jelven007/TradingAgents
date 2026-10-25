# 数据模型与接口契约

状态：2026-10-25。面向后端/客户端/QA，由后端责任角色依据DTO、HTTP和存储实现维护，接口/表/状态码变化时及合并前复核。开头及“当前接口”段是本机reference；编号1–3的领域实体/目标API表是生产候选，不能用于调用本机服务。正式OpenAPI和云迁移治理仍待建。

本地表包括tasks/attempts/model_calls/task_events、reports/report_events、identities/access_events、controls/cost_events、experiments/predictions/observations。金额为整数micro-USD，仓位和观察收益用Decimal字符串。计划固定样本、研究契约、模板hash、显式session序列及价格口径；预测绑定已接受报告与复核事件hash，观察追加并保留来源文本/输入hash。相同session冲突拒绝，修正须另立实验。

本地路径为 `root/workspace/experiment/task/attempt`；幂等为工作空间+作者+键，HTTP成功统一200、任务幂等冲突400、模型设置版本冲突409、未知对象404、跨空间403。API没有 `/api/v1` 前缀、签名下载、health、生产审批生效接口或自动网格调度。客户端workspace须与凭据一致，操作者由token取得；上述差异不代表生产目标已实现。

本地模型配置为`model_revisions`不可变公共版本、`model_active`工作空间当前指针及`model_credentials`密文表。`GET /settings/models`要求settings:read；`POST /settings/models`和`POST /settings/models/test`要求settings:write。保存body包含expected_version和quick/deep两组provider/model/base_url/api_key/clear_api_key/api_version；测试body只包含expected_version、tier和所选层的settings对象，另一层未填完不阻止测试。成功统一200，冲突409，普通用户403；响应和审计不包含密钥。配置保存后新任务冻结revision ID及公开模型字段，worker在执行上下文单独读密钥。

本机浏览器认证增加`browser_accounts`（username唯一、随机ID、workspace、role、salt/password_hash）、`browser_sessions`（token_hash、账号引用、csrf、expires）和失败限流表。CLI单工作空间服务显式开启`/auth/status`、`/auth/setup`、`/auth/login`、`/auth/session`、`/auth/logout`；首次创建原子保证只有一个管理员，后续`GET/POST /accounts`需accounts:manage。会话回复只包含账号公开字段、业务scopes和CSRF，cookie保存会话token且HttpOnly；登录/账号密码不进入响应或审计。`/session`提供research_today UTC日期，前端默认研究日与后端门禁一致。完整请求和会话约束见[工作台手册](../03-development/web-workbench.md)。

`POST /research`组合任务创建、指定执行和成功后自动登记报告，要求三个对应scope；原`POST /tasks`保留仅创建行为。任务事件保存自动报告意图及批准的研究阶段名称，详情返回stage列表、调用数/上限和report_id；worker及服务重启补齐未登记的成功结果，报告作者固定为任务作者。`/demo/enter`、`/demo/session`、`/demo/role`及`/demo/`业务路由仅操作每个演示会话独立的合成库，cookie/CSRF与正式账号分开，演示身份不能授权正式接口。

2026-10-25增加 `research_revisions/research_active` 和 `GET/POST /settings/research`：模板公开参数按工作空间不可变版本保存，激活采用expected_version，冲突409。会话返回同源默认值、允许范围与模型摘要，任务接收受模板约束的options和账户allocation_valuation；错误可返回安全fields位置/原因，任务和报告可读取固定输入摘要。来源许可、质量策略、密钥和任意运行配置不属于此公开模板接口。完整字段及操作契约见[研究输入](../03-development/research-inputs.md)。

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

## 5. 已实现的本机入门接口（2026-10-25）

前述`/api/v1`为生产设计。当前loopback服务使用下列无前缀路由，密码会话与CSRF沿用工作台契约；演示对应`/demo/...`，身份和数据库均隔离。

| 方法 / 路径 | 当前行为 |
|---|---|
| GET `/session`、`/auth/session` | 返回实际权限、模板、股票目录元数据与小量选择建议；完整目录不进入响应 |
| GET `/instruments?q=...&market=US/CN/HK&limit=...&offset=...` | `task:read`鉴权；按名称/别名/代码分页搜索，limit为1–100，按可信模板过滤允许范围 |
| GET `/watchlist` | 当前身份的关注、笔记及本人最近八份任务；每个关注对象关联本人的真实最近任务/报告 |
| POST `/watchlist` | 严格接收`action: add/remove/save_note`、`symbol`、`note`；拒绝`subject`或`workspace`等额外字段 |
| GET `/reports/{id}` | 完成授权与固定文件完整性核验后，增加只读`brief`，保留原正文、质量、输入和复核记录 |

`investor_watchlist`以`workspace + subject + symbol`唯一，SQLite事务控制最多100个关注对象，笔记最多4000字符。重复添加保留原笔记；批准清单改变后已有笔记仍可读取、编辑和移除，重新研究须重新校验范围。读取需要`task:read`，写入需要`task:create`；请求不能选择另一所有者。

`brief`只节选固定报告原文和已核验的结构化证据，不额外调用模型。缺少支持、反方或风险原文时明确返回`provided: false`；有价格冲突、过期、未来日期、未知币种或缺少核验行情时不提供价格。价格附研究日、币种、来源及合成标志，界面不将其称为实时行情。实现及验收见[入门投资者改进](../03-development/beginner-investor.md)。

股票快捷任务固定`execution_mode=guided_stock`、`stock_question`、`display_currency`与选择的证券资料；专业完整路线仍是原API默认值。报价币种与显示币种分离，`brief.converted_price`只从已核验的汇率blob计算，包含汇率和日期；无有效汇率则为空。`research_status=insufficient`与普通Hold区分，预算预留必须容纳最多8次调用。目录授权由`research_policy.allow_listed_stocks`可信配置控制，公开模板不能改写该许可；旧任务不会因目录或模板更新而改变。见[股票研究执行契约](../03-development/stock-research-usability.md)。
