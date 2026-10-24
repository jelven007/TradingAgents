# 优化实施与逐轮验证记录

启动日期：2026-10-24；代码基线：`9dd5b06`；依据：[优化建议书](../00-overview/optimization-proposal.md)。

用户已授权按建议逐步实现，并要求每轮至少两次校验后才能继续。本轮迭代采用三个门禁：①新增能力及异常边界测试；②现有离线完整回归；③lint、文档及适用的安装/操作验证。任一失败先修正、重新验证，再进入下一轮。

## 迭代安排

| 轮次 | 交付 | 主要边界 | 状态 |
|---|---|---|---|
| 1 | 结构化研究契约、期限/基准传递、持仓输入校验 | 保留旧SDK/CLI；日级分析不声称支持盘中时间精度 | 完成，三项校验通过 |
| 2 | 证据内容留存、完整性校验、实验/任务隔离 | 留存实际工具输入输出；未知披露时间不伪造；来源许可由运行者配置 | 完成，三项校验通过 |
| 3 | 独立质量规则、报告manifest、复核/发布约束 | 对缺失/冲突/未结构化数值保守处理；不冒充订单风控 | 完成，三项校验通过 |
| 4 | 持久任务与本地worker、幂等、租约、取消及预算 | 单机可运行、进程隔离；外部模型调用不承诺exactly-once | 完成，三项校验通过 |
| 5 | CLI/API接入、授权范围、运营查询、备份恢复 | 本地验证不代替公司OIDC/托管数据库及云灾备验收 | 完成，三项校验通过 |
| 6 | 期限一致的评估、前瞻记录、完整闭环验收与文档同步 | 真实长期观察/数据许可/生产SLO不能由离线替身证明 | 完成，三项校验通过 |

## 验证记录

每轮完成后在此追加实际命令、结果、排除项和关键修正。生产外部依赖尚未提供时，完成可运行本地实现与契约，明确保留上线验收项，不将设计、mock或短时验证当作生产效果。

### 迭代1：研究契约与输入正确性

- 实现：新增 `domain.research.ResearchMandate`；契约固定标的、分析日、预测期限、基准、币种、用途和有效期；进入Agent上下文、LangGraph状态、JSON状态日志和Markdown/HTML报告；观察期限/基准与契约一致；图使用配置深拷贝。持仓拒绝非有限值、重复证券、负成本和未知字段；补充直接Pydantic依赖。
- 校验1：`.venv/bin/python -m pytest -q tests/unit/test_research_mandate.py tests/unit/test_portfolio_context.py tests/system/test_graph_end_to_end.py` → **57 passed**。
- 校验2：`.venv/bin/python -m pytest -q` → **1383 passed，100 subtests passed，1 skipped，1 deselected**，35.99秒。
- 校验3：ruff全仓检查通过；文档检查 **30 documents OK**；锁文件重建和运行依赖导出完成，未升级已锁定包版本。
- 排除：Bedrock未安装extra，真实网络integration默认排除；尚未执行真实模型/行情或盘中/交易所日历验收。契约只支持daily，未知输入不装作已经实现。
- 日志：工作区 `.cache/iteration-1-targeted.txt`、`.cache/iteration-1-regression.txt`。三项检查通过后开始迭代2。

### 迭代2：证据与隔离

- 实现：新增原子不可覆盖文件存储、内容去重及 SHA-256 验证、运行级 ContextVar 证据采集、托管运行适配器；覆盖 router、校验快照、证券身份、社交预取及记忆上下文。配置/输入、状态、证据、报告形成 manifest；工作空间/实验/task/attempt 目录独立。托管运行关闭前台结算且不导入其他运行的未复核记忆。
- 校验1：`.venv/bin/python -m pytest -q tests/unit/test_evidence.py tests/unit/test_vendor_routing.py tests/unit/test_yahoo_snapshot.py tests/system/test_graph_end_to_end.py` → **42 passed**，7.43秒；包括24个并发采集、供应商失败切换、篡改/磁盘失败、路径越界、真实图两实验隔离。
- 校验2：完整离线回归 → **1396 passed，100 subtests passed，1 skipped，1 deselected**，27.04秒。
- 校验3：ruff全仓检查通过；文档检查 **31 documents OK**。
- 边界：工具实际输出留存并不构成完整历史档案；供应商内部缓存时间、披露时间与许可未核实时明确 unknown；本地不可覆盖写入不是防管理员篡改的WORM。通过全部门禁后进入迭代3。
- 日志：`.cache/iteration-2-targeted.txt`、`.cache/iteration-2-regression.txt`。

### 迭代3：独立质量与复核

- 实现：行情快照同时记录未四舍五入的结构化数据；独立检查准入、研究身份/日期、OHLCV、有限值、价格时效/冲突/币种、来源许可及明确价格字段；Decimal计算仓位，未估值账户不放行账户建议。报告保存quality、代码/prompt/schema及依赖指纹。SQLite保存不可改写版本与链式复核事件，禁止自审、过期/未复核发布、硬规则豁免；修订关联旧版，撤回保留内容。
- 校验1：`.venv/bin/python -m pytest -q tests/unit/test_research_quality.py tests/unit/test_report_lifecycle.py tests/system/test_graph_end_to_end.py` → **56 passed**，7.75秒；包括真实图生成至本地复核发布、篡改、作者自审、过期、跨工作空间修订、NaN/Infinity及集中度/只做多边界。
- 校验2：完整离线回归 → **1435 passed，100 subtests passed，1 skipped，1 deselected**，37.85秒。
- 校验3：ruff全仓通过（修正一处测试的dict构造风格后复验）；文档 **31 documents OK**。
- 边界：确定性检查不能证明全部自然语言数值/论据正确，明确保留人工确认项；actor字段在可信存储层不是认证，网络权限将在迭代5实现；本地发布测试不代表金融业务审批。全部门禁通过后进入迭代4。
- 日志：`.cache/iteration-3-targeted.txt`、`.cache/iteration-3-regression.txt`。

### 迭代4：持久任务与调用控制

- 实现：SQLite保存冻结输入、幂等键、attempt与调用账本；原子领取、租约续期/重领、总deadline、并发门禁及条件结果提交。spawn子进程隔离研究，取消/超时终止，子进程自查租约。调用前原子预留预算，重试/取消/失败保留费用unknown；SDK内部重试关闭、输出token有上限。实现指纹在提交/执行前/执行结束校验。
- 校验1：`.venv/bin/python -m pytest -q tests/unit/test_managed_tasks.py tests/system/test_graph_end_to_end.py` → **29 passed**，12.44秒；包括16个并发幂等/领取、并发预算、旧attempt、取消、deadline、挂起/崩溃子进程及真实图调用接线/唯一接受。
- 校验2：完整离线回归 → **1446 passed，100 subtests passed，1 skipped，1 deselected**，33.38秒。
- 校验3：ruff全仓通过；文档 **31 documents OK**。
- 修正：首次专项发现测试模型的Pydantic构造复制了计数列表，改为逐模型汇总实际生成调用，再完成专项及回归；没有绕过断言。独立预算耗尽标志阻断图内兼容回退后的结果提交。
- 边界：预算预留不是供应商账单；在途请求仍可能计费，不承诺外部exactly-once。worker并发参数需部署一致，单机数据库不等于云队列。全部门禁通过后进入迭代5。
- 日志：`.cache/iteration-4-targeted.txt`、`.cache/iteration-4-regression.txt`。

### 迭代5：授权入口、运营与恢复

- 实现：新增兼容CLI的managed子命令及仅loopback的JSON API；本地短期可撤销token仅存hash，工作空间/scopes授权，操作者不可由请求伪造。管理员模板固定配置，事务检查工作空间累计准入预算/积压、暂停提交及冻结发布。版本登记幂等，模型费用一次性账单对账、unknown单列，访问审计含request_id。
- 校验1：`.venv/bin/python -m pytest -q tests/system/test_managed_service.py tests/unit/test_report_lifecycle.py` → **14 passed**，3.85秒；包括真实本机HTTP、跨空间/权限/自审拒绝、配置/actor注入拒绝、并发准入、发布开关、费用冲突、备份hash、恢复报告/证据/审计/费用及旧attempt/凭据失效。
- 校验2：完整离线回归 → **1452 passed，100 subtests passed，1 skipped，1 deselected**，39.51秒。
- 校验3：ruff全仓与diff格式通过；文档 **31 documents OK**；managed CLI及control帮助命令通过。
- 修正：首轮专项发现离线fixture阻止本机HTTP与CLI幂等键缺少选项声明；新增仅127.0.0.1的测试fixture，保留其他socket/curl外网阻断，修正`--key`后重新通过全部检查。
- 恢复边界：一致SQLite快照与已接受对象复制到新目录，副本queued/running全部fence为cancelled、凭据撤销，原库不动，不自动重启外部调用。本地演练不证明云RPO/RTO、OIDC/TLS或托管基础设施；费用查询不含数据、基建与人工全成本。全部门禁通过后进入迭代6。
- 日志：`.cache/iteration-5-targeted.txt`、`.cache/iteration-5-regression.txt`。

### 迭代6：期限评估、前瞻记录与最终闭环

- 实现：固定实验样本/模板hash、研究契约、显式session日历和价格口径；预测绑定已接受报告/复核事件hash，观察保存Decimal原值/来源文本与hash且不可覆盖。前瞻计划早于研究日、报告发布及预测固定早于入口session，核对全部时间顺序；历史diagnostic明确模型事后知识unknown。同币种同起止日的标的/基准收益及差值，短窗口仅interim，完整计划/未提交/失败/取消/REVIEW/pending/撤回保留；不拼策略净值/Sharpe。
- 校验1：`.venv/bin/python -m pytest -q tests/unit/test_research_evaluation.py tests/system/test_managed_service.py tests/unit/test_report_lifecycle.py tests/system/test_graph_end_to_end.py` → **65 passed**，12.59秒。覆盖真正LangGraph离线运行→任务/模型账本→消费证据→规则→复核/发布→固定预测→收益观察→备份恢复、真实本机HTTP授权、前瞻时点、同窗口/币种/复权、冲突/篡改及完整分母。
- 校验2：完整离线回归 → **1482 passed，100 subtests passed，1 skipped，1 deselected，20 warnings**，35.33秒。
- 校验3：ruff全仓、diff格式、文档 **31 documents OK**；sdist/wheel构建成功。工作区独立新环境hash安装85个默认锁依赖与wheel，cwd为`/private/tmp`、Python3.13.17 `-I`验证18个新增相关模块来自site-packages、welcome/logo资源、无dev依赖；console script及managed帮助成功。
- 修正：首轮42项边界测试通过；lint发现两处import顺序及一处测试表达风格，修正后加上真实图闭环和“事后生成不能转前瞻”用例，完成最终65项专项、全量回归及门禁。模板hash纳入任务强制重试/token设置，避免计划与实际执行口径不同。最终打包检查补齐MANIFEST中的config JSON示例，重建并核对sdist文档/示例与wheel/安装内容。
- 文档：PRD、追踪矩阵、开发计划、架构/接口/安全/数据治理、测试/验收、运营、部署/观测/故障/恢复及变更状态同步为本地实现；[托管手册](managed-research.md)与示例补充评估入口。原生产阶段签署条件不冒充完成。
- 边界：前瞻时点正向测试为合成时钟，行情/模型均离线替身；session序列及价格来源文本由运营者提供，hash不证明真实性/许可或内置交易所日历。真实长期前瞻、完整历史档案、自动网格/反馈平台、公司OIDC/云基础设施、全成本与生产SLO/RPO/RTO仍需后续验收。本轮未重验镜像/多平台、未新增commit/push/部署。
- 日志：`.cache/iteration-6-{targeted,regression,build,wheel-install,wheel-check,managed-help,cli-help}.txt`；包 `.cache/iteration-6-dist`。六轮均完成三门禁，详细最终结果见[验证记录](../04-testing/validation-report.md)。
