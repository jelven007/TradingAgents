# 托管研究本地运行

本地实现状态与逐轮检查见[迭代记录](iteration-log.md)。已有 `TradingAgentsGraph` SDK 和交互 CLI 保持兼容，新增托管入口逐步提供固定研究契约、证据、质量检查、任务与复核能力。

## 契约与证据

`application.runs.execute_research(root, scope, mandate, config)` 接受 `ResearchMandate` 和 `RunScope(workspace, experiment, task, attempt)`。运行目录为 `root/workspace/experiment/task/attempt`；各层标识限制为 ASCII 字母、数字、下划线和短横线。相同 attempt 再次执行直接拒绝，重试必须使用新 attempt。

每次运行使用独立数据缓存、checkpoint 设置、记忆日志和结果目录。托管运行不自动结算旧记忆，也不载入其他实验或未复核的经验；旧 SDK 的行为保持不变。供应商库自身可能使用进程级网络缓存，留存的是本次实际消费的结果，不能把缓存读取时间称作供应商抓取时间。

生成的主要文件：

| 文件 | 用途 |
|---|---|
| `input.json` | 固定研究契约、输入持仓、实验标识、完整配置 hash |
| `evidence/manifest.json` | 来源、工具名、参数、内容 hash、观察时间、许可标签 |
| `evidence/blobs/<sha256>.json` | 实际工具返回值，重复内容只保存一份 |
| `state.json` | 可 JSON 序列化的决策状态 |
| `report/` | SDK 生成的 Markdown 与 HTML 报告 |
| `run.json` | 完成状态、模型设置、报告与证据文件 hash |
| `failure.json` | 失败时间及错误类型；不记录可能含密钥的异常原文 |

`source_licenses` 为运营者配置的 `来源名称 → 许可标签` 字典；未配置记为 `unknown`，它不是许可授权。只有获得许可的数据才应配置为可存储来源。来源实际输出可能包含受许可或敏感内容，部署者负责存储权限与生命周期。

捕获范围包括数据路由实际命中的 vendor 和失败类型、行情校验快照、情绪分析预取内容、证券身份提示以及本次读取的记忆上下文。`observed_at` 表示系统消费时间；`fetched_at`、`known_at`、`published_at` 无可靠元数据时为 null。该留存不等于完整历史行情档案，也不证明历史回测消除了模型事后知识。

`verify_bundle(path, expected_hash)` 校验证据 manifest 和全部内容对象；预期 hash 应取自已接受任务或复核记录。文件采用原子创建且拒绝覆盖，但本地 OS 管理员仍可改写文件，因此这属于带外部 hash 锚点的完整性检查，不是 WORM 存储或数字签名。

## 独立质量与固定版本复核

`config["research_policy"]` 接受 `domain.quality.ResearchPolicy` 的 JSON 字段：`version`、`approved_tickers`、`max_price_age_calendar_days`、`require_licensed_sources`、`long_only`、`max_position_weight`。默认批准标的为空，默认要求来源许可标签，因此未配置的运行只形成受阻草稿。许可标签是运营者声明，不能代替供应商合同验证。

数值检查读取行情适配器产出的原始结构化 OHLCV 证据，不从 LLM 自由文本猜价格。覆盖身份、研究日、未来/陈旧价格、OHLC 范围、有限值、成交量、同日价格冲突和明确的价格字段。`quality.json` 与 `report/quality.md` 保存独立规则结果及计算输入引用。无法确认的币种/披露时间、缺失来源、未绑定计算对象的自然语言结论进入人工核验；不因五档评级可解析就认定研究合格。

配置的日历天陈旧阈值是本地规则，不等于已经集成交易所节假日历。当前 Yahoo 快照不提供可独立核验的币种字段，保留 null，并要求复核；账户配置计算必须有币种和当日价格证据。`AllocationInput` 明确价格、权益、当前/变化数量、日期、币种及证据 hash，使用 Decimal 计算目标名义金额和权益占比，校验只做多和集中度。SDK 的原持仓对象缺少完整估值，不能自动生成该对象。

`infrastructure.reports.ReportStore` 在 SQLite 中登记固定 `run.json` hash，提供状态：

`draft → approved → published → withdrawn`；草稿也可退回 `rejected` 或撤回。退回后通过新版本修订，`supersedes` 保留旧版本关系。

登记接口为 `register(run_path, manifest_hash, author, supersedes=None)`；流转接口为 `transition(report_id, action, actor, reason, acknowledgements=[])`。作者不能自审；批准必须逐项确认 quality 中所有 `review` 类别，`block` 类别不能豁免；到期报告不能批准或发布；批准和发布均重新验证报告与证据。数据库禁止改写版本与审核事件，事件带链式 hash。撤回不会删除原报告，读取时同时返回 `expired` 标志。

这些是可信本地存储接口，actor 参数本身不是身份认证。接入网络服务时必须通过授权应用层，不能把存储类直接暴露给请求。离线复核测试只验证程序门禁，不代表真实研究负责人已经批准任何报告。

运行 manifest 另记录 Python 源文件（包含 Agent 提示词/schema）hash、包版本和关键依赖版本。结合输入配置 hash 可以定位实际实现；云镜像、模型厂商不可变版本与训练截止信息仍需外部补充。

## 持久任务、worker与预算

`domain.tasks.TaskInput` 固定工作空间、实验、契约、配置、分析师、持仓/估值和 `TaskLimits`。`infrastructure.tasks.TaskStore.submit(input, author, idem_key)` 在SQLite保存输入及实现指纹；同工作空间、作者、幂等键且输入一致时返回原任务，输入冲突拒绝。任务配置的SDK内部重试固定为0、输出token上限由limits控制，避免内部重试绕过调用账本。数据库含配置，请使用环境凭证并限制本地目录权限。

`application.worker.run_one(store, root, worker)` 原子领取一个任务，以spawn独立子进程运行图，父进程续租并在取消/超时后终止子进程；子进程检查租约，父进程丢失后也有退出边界。任务状态为 `queued/running/succeeded/failed/cancelled/timed_out`。租约过期可在总deadline内重新领取，超过最大attempt数则失败。普通执行错误保留失败终态，修正后新建任务。领取的并发上限是可信worker配置，同一部署须一致；不是多机队列服务。

仅当前且未过期attempt可条件提交结果；完成时核对scope、契约、配置、输入及实现指纹，并验证全部文件/证据hash。开始前及结束时检测实现变化，不混合新旧源码结果；旧attempt留下的对象保留供调查，不会成为已接受结果。

每次LangChain模型调用前原子预留micro-USD并检查总调用数、任务总预算和deadline；调用后保留厂商提供的token usage。取消、租约失效及失败不会退回已预留预算，重试继承任务累计消耗。`reserve_per_call_microusd` 是运营者设置的保守准入额，必须按模型和最大输入/输出核定，不能称为真实账单或保证费用预测准确；实际费用未知保留null，后续对账。超预算标志独立阻止结果接受，即使模型回调异常被图中兼容回退捕获。已经发出的请求仍可能被供应商计费；本实现不承诺外部调用exactly-once。

## 有范围的CLI与本机API

新增 `tradingagents managed`，也可用 `.venv/bin/python -m cli.main managed`。默认数据库为 `runtime/research.sqlite`，对象为 `runtime/artifacts`。配置入口 `--db/--artifacts/--templates` 必须置于子命令前；它们由可信本地运营者管理，不是网络请求字段。

运营者模板以工作空间和模板名称索引，示例为[模板](../../config/examples/managed-templates.json)及[任务请求](../../config/examples/managed-request.json)。模板覆盖原SDK默认配置，在服务启动及任务提交时冻结；例子没有声明真实来源许可，因此生成的报告可能受阻。请按实际授权核定标的、数据来源与预算。工作空间预算是本地库中**所有已准入任务预算的累计上限**，取消不释放；不是月度账单限额。待执行任务数和累计预算在同一个提交事务内检查。

本地身份由运营者发放随机token，数据库仅保存hash，可撤销、最长有效一天；subject统一小写ASCII标识，防止作者使用大小写变体自审。每个凭据只授予一个工作空间及明确scopes。公开入口从凭据取得操作者，不接受author/actor、任意config、模型URL、策略、路径或预算覆盖。公司OIDC、TLS网关、集中身份与账户级授权仍是生产接入工作；本机token方案不能称作OIDC验收。

```bash
# 可信本地运营者创建凭据。不要把token文件或运行数据库提交到Git。
tradingagents managed identity-issue author research \
  task:create,task:read,task:cancel,report:register,report:read runtime/author.token
export TA_RESEARCH_TOKEN="$(cat runtime/author.token)"
tradingagents managed --templates config/examples/managed-templates.json \
  submit config/examples/managed-request.json --key baseline-20261023
tradingagents managed task <task-id>
tradingagents managed worker --max-tasks 1
tradingagents managed register <task-id>
```

worker、serve、identity-issue/revoke、backup/restore 是持有本地文件权限的运营命令。用户操作使用环境变量 `TA_RESEARCH_TOKEN`，避免token成为CLI参数。另发 reviewer（`report:read,report:review`）、publisher（`report:publish`）或operator（`ops:read,ops:control,cost:reconcile,audit:read`）凭据；不要向普通用户分发数据库访问权限。

复核命令为 `review <report-id> approved "<reason>" --acknowledge <quality中review代码的逗号列表>`；发布使用 `review <report-id> published "<reason>"`；撤回需 `report:withdraw`。`operations`显示任务完整分母、所有终态、复核积压、过期报告、预留金额、已对账金额和未知费用数，调用明细最多200条；仅覆盖模型调用，数据/基础设施/人工成本未纳入。`reconcile <call-id> <micro-USD整数> <invoice-line-ref>`一次性固定实际费用，同账单重复提交幂等，冲突拒绝，unknown不是0。

`control pause_submissions --enabled "<reason>"` 暂停新准入；`control freeze_publication --enabled "<reason>"` 冻结发布；恢复使用 `--no-enabled`。发布控制与报告流转在同一事务检查，暂停不妨碍原幂等请求查询。控制原因和访问记录可通过独立 `audit:read` 查询；HTTP操作具有关联request_id。审计是本地追加记录，不是防管理员改写存储。

`serve --port 8765`仅绑定`127.0.0.1`，worker另开进程。本机HTTP的请求body上限64KiB、连接超时5秒、最多16个请求线程。API返回JSON，不提供自动外部发布/消息分发。所有端点要求`Authorization: Bearer <token>`：

| 方法和路径 | 输入 / 权限 |
|---|---|
| `POST /tasks` | 请求示例；`Idempotency-Key`；`task:create` |
| `GET /tasks/<id>`、`POST /tasks/<id>/cancel` | `task:read` / `task:cancel` |
| `POST /tasks/<id>/report` | `{supersedes?: id}`；仅已接受结果；`report:register` |
| `GET /reports/<id>` | quality与Markdown正文；`report:read` |
| `POST /reports/<id>/review` | `{action, reason, acknowledgements}`；对应复核/发布/撤回scope |
| `GET /operations`、`GET /audit` | `ops:read` / `audit:read` |
| `POST /controls` | `{kind, enabled, reason}`；`ops:control` |
| `POST /calls/<id>/reconcile` | `{amount_microusd, invoice_ref}`；`cost:reconcile` |

权限错误403，认证错误401，非法输入400，幂等冲突400，容量/预算拒绝429，未知对象404；异常输出只含错误类型，不回显请求/凭证/配置。报告读取重新验证内容hash。错误和拒绝响应不构成金融业务批准。

## 可验证的本地备份恢复

`backup <新目录>`使用SQLite backup API形成一致事务快照，保存已接受运行/报告所引用的输入、状态、质量、证据对象与报告hash，输出 `backup_sha256`；不复制未接受attempt、可重建缓存、旧SDK独立memory或个人登录文件。数据库可能含研究输入和运营配置，应使用环境凭证，并将备份置于实际受控加密存储；本命令不实现云加密或异地灾备。

`restore <备份目录> <backup_sha256> <新恢复目录>`先核验外部保存的hash及每个文件，在暂存目录校验SQLite、输入、复核链及证据，再整体启用。仅修改副本的路径引用，原库不动；恢复副本里的queued/running任务全部取消并记录RecoveryFence，旧凭据撤销，费用unknown保留。运营者重新发放凭据并明确新建任务后才会再执行研究。新目录已存在时拒绝覆盖，缺失/篡改备份拒绝启动。

恢复后的数据库为 `<新恢复目录>/store.sqlite`，对象目录为 `<新恢复目录>/artifacts`。本地离线演练验证完整性与旧attempt隔离，不证明生产RPO/RTO、跨故障域或长期灾备可用性；这些仍需在目标环境测量。

## 固定实验计划、前瞻登记与期限观察

新增 `domain.evaluation` 和 `infrastructure.evaluations.EvaluationStore`。计划、预测和观察以SQLite追加记录、不可更新/删除的trigger和SHA-256关联保存，备份/恢复同时校验这些记录。与本地证据相同，这不是防OS管理员篡改的WORM。

计划为 `ExperimentPlan(workspace, experiment, mode, samples, price_basis, calendar_source, calendar_evidence)`。每个sample固定key、template、ResearchMandate和sessions；sessions为严格递增的**入口session加完整预测期限**，长度等于horizon+1，入口在研究日后且在研究有效期内。计划还冻结管理员模板的配置/分析师/限制hash（包含TaskStore强制的重试/token设置）。提交任务使用sample.key作为幂等键，mandate/template必须一致；同计划样本跨作者重复创建也拒绝，模板变更需新实验。

`prospective`计划必须在所有样本研究日的UTC零点前登记，不能接管已存在任务。未来日可登记计划，实际任务仍拒绝未来分析日。预测登记要求已接受任务、固定报告、独立复核后published状态；核对计划→任务创建→研究完成→发布→登记的时间顺序，且早于入口session。系统以daily和UTC标签采取保守日门禁，不声称具备盘中cutoff精度。错过登记窗口后仍保留计划及缺失样本，不允许改为提前登记。

`diagnostic`可以登记历史任务或未发布草稿。报告评级/quality/复核状态保留原值，REVIEW和blocked不会变成Hold或合格研究；历史模型事后知识始终标为unknown。它是历史诊断，不是已消除模型训练信息泄漏的严格回测。计划同名同内容可重复查询，内容冲突拒绝；一个样本只能固定一个预测。历史未计划任务和同key多任务分别显示unplanned/ambiguous数量。

观察输入为 `ObservationInput(entry_session, exit_session, asset, benchmark, source, source_payload)`。asset/benchmark各含symbol、currency、basis、entry、exit；价格要求有限正Decimal字符串或整数，拒绝float和bool，最多12位小数。必须使用同入口日、同出口日、同币种及同价格口径，且出口在计划sessions内；只能在出口UTC日期结束后登记。系统没有交易所日历或行情抓取器，输入session与来源文本由运营者核定；source文本hash与完整输入hash证明留存一致性，不能证明价格真实性或商业许可。

支持 `unadjusted_close`、`split_adjusted_close`、`total_return_index`，不混用复权和总收益口径。用50位Decimal上下文计算 `asset_exit/asset_entry-1`、基准对应收益及两者之差，保留原小数字符串；未纳入仓位、融资、费用或成交。短于horizon的窗口标为interim，只有完整窗口标为final；final仅代表期限覆盖，不给研究结论打最终正确性标签。重复同session同输入返回旧记录，不同输入拒绝；不同窗口入口价格必须相同，纠错需新实验，不能覆盖历史。

`experiment`统计全部计划样本、未提交、全部任务终态、评级（含REVIEW）、报告当前状态（含撤回）、预测数及interim/final/pending覆盖；pending包含尚未完成完整窗口的样本，不作为零收益。观察在报告撤回后仍保留，当前撤回状态单列，不将这些观察拼成策略净值或Sharpe。暂不提供自动网格调度、长期统计推断或反馈管理。

授权为 `evaluation:write`（计划/预测/观察）、`evaluation:read`（计划分母与预测/观察读取），scope会暴露相应研究数据，应按职责授予。CLI示例文件的行情为合成值，不能作为真实业绩：

```bash
tradingagents managed --templates config/examples/managed-templates.json \
  plan config/examples/managed-plan.json
# 使用计划中相同experiment/mandate/template及sample.key提交任务，执行worker并登记固定报告。
tradingagents managed predict <experiment-id> <task-id> <report-id>
tradingagents managed observe <prediction-id> config/examples/managed-observation.json
tradingagents managed experiment <experiment-id>
tradingagents managed prediction <prediction-id>
```

| 方法和路径 | 输入 / 权限 |
|---|---|
| `POST /experiments` | ExperimentPlan；`evaluation:write` |
| `GET /experiments/<id>` | 完整计划分母与覆盖；`evaluation:read` |
| `POST /experiments/<id>/predictions` | `{task_id, report_id}`；`evaluation:write` |
| `GET /predictions/<id>` | 固定预测和全部观察；`evaluation:read` |
| `POST /predictions/<id>/observations` | ObservationInput；`evaluation:write` |

真实图离线闭环、时间/价格边界、本机HTTP授权、immutable冲突和恢复在system/unit测试中验证；前瞻正向时点测试使用明确合成时钟，不冒充真实长期观测。生产数据许可/行情真实性、OIDC、目标环境容量与SLO、长期金融有效性仍需外部验收。
