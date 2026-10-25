# 本次工程验证记录

核对日期：2026-10-25；本reference面向QA/发布读者，QA责任角色只追加已执行证据、保留旧日期。每次交付/合并前新运行验证，下面历史章节的“未提交/未调用”只适用于当时。当前合并结果以Git/PR/CI为真相，不用本地命令代替远端通过或生产验收。

日期：2026-10-23；来源 `e8f5503e9b86d5c2710b0c76b1f686703968c9df`；本地分支 `chore/production-foundation`。检查针对未提交工作区，不等于远端CI或生产验收。

## 1. 环境与产物

macOS arm64，系统Python3.9.6不足以运行本项目；本次在工作区内准备CPython3.13.17、uv0.13.5及 `.venv`，ruff0.17.2。生成 `uv.lock`及带hash的默认运行依赖 `requirements.lock`；Docker使用Python3.13 Linux arm64运行环境。

目录迁移保持 `tradingagents.*` 与 `cli.*` 导入、console script和package data。源码分层测试显式扫描src且断言数据目录非空；发布版本读取路径同步修正。MANIFEST包含开发/测试/文档/部署材料，wheel只安装包及其资源。

## 2. 实际执行

| 检查 | 结果 |
|---|---|
| 远端默认分支HEAD、clone与本地版本 | main / e8f5503 / 0.7.0 |
| 第一次默认离线测试 | 1358 passed、3 failed、1 skipped、1 deselected、100 subtests passed |
| 首次失败根因 | macOS errno没有EDEADLOCK别名；使用标准EDEADLK修复Windows锁逻辑与模拟用例 |
| 修复后完整回归 | 1361 passed、1 skipped、1 deselected、100 subtests passed，31.26秒；20条模型目录警告 |
| ruff | `python -m ruff check .`通过 |
| 文档链接/编号 | 28份维护文档（含根README）通过；15项FR、8项NFR与矩阵一致 |
| sdist/wheel | `python -m build`成功；生成0.7.0源码包与wheel |
| 仓库外wheel/CLI/资源 | 在独立无dev依赖环境安装hash锁及wheel，cwd为/tmp；import、help、welcome、logo均通过，确认来自site-packages |
| Docker构建/非root/help | Linux arm64构建成功；`--network none`验证help、uid1000、package资源；最终层无/build、源码与.env |
| Compose配置路径 | `--profile ollama config --no-env-resolution`通过，build context及.env路径正确；未配置真实.env或启动服务 |
| 文件保全与Git忽略 | 95个包/资源文件均存在，仅files.py标准errno别名修复；环境模板可被Git追踪，本地工具被忽略 |

## 3. 额外修正说明

标准错误码修复未改变锁等待、非阻塞或错误抛出的语义；没有通过skip规避失败。源码算法、提示词和评级逻辑没有因目录重排批量改写。镜像按依赖锁安装，最终层不包含源码/文档/环境凭据。

本地镜像：`tradingagents:production-foundation`，构建manifest摘要 `sha256:77e7336c7b09bc840d9aab18c1da94891c07781cc73bed929c84503c468d9f60`。Python3.13.17工具、测试日志及独立wheel环境保留在被忽略的工作区目录；报告不将这些临时工具当作项目源码。

## 4. 未执行或不能据此证明

真实模型/行情调用与交易效果，外部集成测试，Bedrock可选安装，Windows原生运行，Python3.11/3.12/3.14本地矩阵，云部署、多租户权限、真实性能、模型质量评估、生产监控、备份恢复演练和业务签署。上游Bedrock测试因未安装extra跳过，网络integration默认排除。

当前 `0.7.0`表示来源，尚未制定自有发布版本；本次未提交、推送或部署外部服务。S1/S2目标仍在[验收清单](acceptance-checklist.md)保持未完成。

## 5. 2026-10-24六轮优化增量

以上为2026-10-23历史工程基线记录。本增量基于本地 `9dd5b06`，用户授权逐轮实现并要求每轮至少两次校验；六轮均执行专项、完整离线回归、lint/docs三项门禁。每轮数字、修正和边界见[迭代记录](../03-development/iteration-log.md)，当前操作见[托管手册](../03-development/managed-research.md)。

| 最终检查 | 实际结果 |
|---|---|
| R6专项 | `test_research_evaluation.py`、`test_managed_service.py`、`test_report_lifecycle.py`、`test_graph_end_to_end.py`：65 passed，12.59秒 |
| 完整离线回归 | 1482 passed、100 subtests passed、1 skipped、1 deselected、20 warnings，35.33秒 |
| 新增闭环 | 真实LangGraph＋离线模型/行情，经任务/调用账本→证据/hash→质量→复核/发布→固定预测→期限收益→备份/恢复；正向前瞻时间门禁为合成时钟 |
| lint / diff / 文档 | ruff全仓、`git diff --check`、31份维护文档本地链接及FR/NFR覆盖通过 |
| 包构建 | 0.7.0 sdist及wheel成功；补齐config JSON示例清单并核对包/安装内容；该值保留来源，不是自有或官方发布 |
| 独立安装 | 工作区内新建无dev环境，hash校验安装85个默认运行依赖及wheel，未升级锁定版本 |
| 仓库外加载 | cwd `/private/tmp`，Python3.13.17 `-I`验证18个模块来自新环境site-packages，welcome/logo资源齐全，pytest/ruff未安装 |
| 仓库外CLI | console script `--help` 与 `python -I -m cli.main managed --help`成功，包含plan/experiment/predict/prediction/observe |

保留日志：`.cache/iteration-6-{targeted,regression,build,wheel-install,wheel-check,managed-help,cli-help}.txt`，安装环境 `.cache/iteration-6-wheel-venv`，包目录 `.cache/iteration-6-dist`。本地工程包括hash恢复、权限负面和范围内完整分母，不再将这些列为全部待建；生产阶段勾选仍保留未完成。

排除与限制：未调用真实模型/行情、真实网络integration仍排除，Bedrock未安装extra仍跳过；未重跑Docker镜像、Windows/其他Python矩阵、云队列/OIDC/TLS/加密/签名下载/厂商速率/完整成本或SLO压测，未证明真实RPO/RTO、数据真实性/许可、完整历史档案、自动网格/反馈系统或长期金融有效性。本轮未新增commit、push或部署，原有运行数据未被用于演练。

## 6. 浏览器工作台增量

基线 `acc6b0e`，用户要求实现可访问交互的Web页面。本地入口为`http://127.0.0.1:8765/`，React/Vite资源由Python服务同源提供；功能及限制见[工作台手册](../03-development/web-workbench.md)。

| 检查 | 实际结果 |
|---|---|
| 后端专项 | workbench HTTP/列表/权限/Origin/Host/执行指定任务/关闭隔离，加上原managed/lifecycle/tasks：31 passed，12.56秒 |
| 全量离线回归 | 1486 passed、100 subtests passed、1 skipped、1 deselected、20 warnings，48.36秒 |
| 构建 | React/Vite 291模块生产构建成功，生成index.html、app.js与style.css |
| 内置浏览器 | 556×672验证凭据文件导入→创建真实queued任务→任务详情/凭据缺失→取消后真实状态更新；无全页横向溢出 |
| Playwright补验 | 内置浏览器没有窗口尺寸控制，补验1440×960及390×844；桌面/手机导航、报告正文、作者自审拦截、独立复核逐项确认/发布、预测绑定与价格观察、暂停恢复、对账和审计均通过，无pageerror |
| 数据边界 | 报告/复核/观察/对账在独立QA库使用明确fixture，主runtime只保留一个已取消UI验收任务；没有真实模型/行情或费用 |
| 视觉 | 截图检查深绿导航、白/灰色层次、中文排版、表格/弹窗/移动抽屉及状态；修正窄屏sr-only定位导致的横向溢出、切页滚动和旧请求返回状态，质量问题补中文说明保留原记录 |
| lint/docs | ruff、diff格式及32份维护文档本地链接/编号覆盖通过 |
| Python包 | 最新sdist/wheel构建通过；独立无dev环境安装wheel后在`/private/tmp`用`-I`核对3个web资源等于源码构建产物，启动已安装HTTP入口返回200，新execution模块来自site-packages |

专项首轮挂起进程用例在并行安装/构建负载下未在2秒deadline前到达调用预留，导致缺少call；没有放宽断言，停下并行负载后复验原测试及新增专项通过，全量回归再次通过。Playwright尺寸切换先等待CSS过渡结束，CSP不允许字符串eval时改为函数谓词；未削弱CSP。

设计概念请求多次仅返回生成中占位图，未用于网页，也不宣称视觉参照匹配。生成的页面有原生文本/表单，无截图代替界面或虚构行情业绩。仍未验收真实模型授权/行情、公司OIDC、TLS云部署、生产负载SLO与长期金融效果；本轮未自动提交或推送。

## 7. 模型设置增量

用户要求可进行模型配置的设置页。本机新版本入口为`http://127.0.0.1:8769/#settings`，使用`runtime/tokens/admin.token`；旧8765本机进程保留，自动审批拒绝停止该进程，故采用独立端口。主库模型配置仍为v0，无测试密钥、无真实模型调用。

| 检查 | 实际结果 |
|---|---|
| 后端专项 | 设置及原workbench/managed服务：33 passed、2条模拟模型目录警告，17.75秒 |
| 全量离线回归 | 1504 passed、100 subtests passed、1 skipped、1 deselected、22 warnings，52.40秒；Bedrock optional未安装仍跳过，网络integration排除 |
| 模型设置 | 密钥Fernet加密、600解密文件、重建store后持久性、留空保留/清除/更换地址、CAS冲突、API错误无密钥、独立scope和旧任务版本固定 |
| worker与恢复 | 同供应商快速/深度模型使用不同密钥且覆盖环境、不改变配置hash；原.env任务兼容；备份公共配置hash/引用校验、解密文件排除、恢复后重新配置 |
| 连接测试 | 真实SDK访问独立loopback HTTP stub：单次成功、401分类、最多64输出tokens、无重试、禁止302重定向、硬deadline终止；未请求真实供应商 |
| 内置浏览器 | 556px真实表单上传凭据→选择兼容供应商→填写→测试成功→保存，密钥框清空并显示已配置；正式8769页面可读，两组模型、无溢出 |
| Playwright | 1440px/390px独立QA库：保存/保留/重连/清除/还原、连接成功/授权失败、Azure字段、只读身份不可保存/测试、移动导航与保存；另验另一层未填完时仍可测试所选层，无pageerror/全页横向溢出 |
| 构建与安装 | Vite 292模块构建；sdist/wheel成功；仓库外`-I`加载来自site-packages，3个web资源等于构建产物，安装后页面/settings GET/单层probe均200 |
| lint/docs/diff | 全仓ruff、diff格式、33份维护文档本地链接通过 |

日志为`runtime/logs/model-settings-{tests,full-tests,build,wheel-check}.log`及`settings-ui-check.json`，截图为`runtime/settings-{ready,desktop,mobile}.png`。初始非隔离build因venv未安装setuptools失败，改用uv隔离构建环境成功；未修改运行依赖锁。首次专项两项断言按SDK真实字段名`deployment_name`/`max_completion_tokens`修正后通过；保留实际输出上限与部署名称验证。

已支持中文快速/深度模型设置、供应商及地址默认值、API Key加密保存/不回显、连接检查、新任务立即生效；已有任务不回写。配置仍未证明厂商模型的工具/长上下文能力或实际研究质量，生产DNS绑定/出口网关、secret manager、审批治理另验。本次未自动commit/push。

## 8. 首页账号登录与权限体验修复

用户从首页无法正常进入页面，现已增加首次本机账号创建、密码登录、刷新保持、退出登录、角色导航和管理员账号管理。当前首页`http://127.0.0.1:8769/`保留用户自己设置账号密码的状态；本机原库未创建测试账号，模型配置和真实调用仍为0。旧8765页面链接到新版；演示库未改写或执行。

| 检查 | 实际结果 |
|---|---|
| 后端专项 | 账号、设置、workbench、managed服务：38 passed，26.84秒；最终账号/workbench复验9 passed，6.91秒 |
| 全量离线回归 | 1509 passed、100 subtests passed、1 skipped、1 deselected、22 warnings，50.80秒 |
| 身份与会话 | 首次管理员并发唯一、salt+scrypt密码hash、错误登录/限流/过期、HttpOnly/SameSite cookie、CSRF拒绝、普通角色越权拒绝、logout及恢复撤销旧会话 |
| 内置浏览器 | 从首页填写账号/确认密码创建管理员→任务/报告/评估/运营/设置逐页正常空状态和配置表单，均无“使用有权限的身份访问” |
| Playwright | 1440px/390px新会话：错误密码提示→登录→刷新保持→全部页面→模型保存/刷新→创建复核员→创建/取消任务→退出→复核员登录及按角色导航；无pageerror/页面横向溢出 |
| 首页与旧入口 | 正式8769保留账号创建，手机第一屏可见完整进入按钮；从8765的“打开新版工作台”可进入8769账号首页 |
| 日期修复 | 实际UI默认浏览器日期跨到次日，UTC后端拒绝未来日期；会话提供research_today并用于默认日期/max，保留未来日门禁，随后UI创建/取消成功 |
| 构建 | Vite 293模块及sdist/wheel成功，运行依赖锁未变；仓库外`-I`确认来自site-packages、3个页面资源一致、账号登录/会话/任务/设置HTTP通过 |

内置浏览器在刷新阶段先出现`IDE Command timeout`，恢复后`WebView is not ready yet`，依浏览器故障流程改用现有Playwright补验。检查脚本和日志为`runtime/verify-login-ui.py`、`runtime/logs/browser-login-{tests,final-tests,full-tests,ui,build}.log`；截图为`runtime/login-{ready-desktop,ready-mobile,home-desktop,settings-mobile}.png`。初次Playwright账号选择器按真实select定位修正；实际任务日期失败按上述UTC根因修复，未放宽后端规则。

安装版设置请求首次加载SDK超过smoke客户端5秒上限，改为有界30秒并插入10秒栈采样后完成，未触发10秒栈输出；结果见`runtime/logs/browser-login-wheel-check.log`。这不证明生产请求延迟SLO。

本机密码账号只服务loopback的单工作空间；生产公司OIDC、密码找回、组织账号禁用/生命周期、TLS及云负载仍另验。报告作者仍不能自审，真实模型/行情未调用；本轮未commit/push。

## 9. 可执行研究闭环与三轮以上交付验证

用户要求系统能够实际操作，且“各种维度校验3次以上都成功，再交付”。最终入口为`http://127.0.0.1:8780/`，首页可直接体验隔离合成演示；正式账号仍由用户创建。页面开始研究实际调用`POST /research`，自动启动指定任务、展示阶段及调用数，成功后生成报告。演示在安装包内运行真实LangGraph与七次离线脚本模型调用，通过现有任务、预算、证据、质量、报告、复核及评估存储。

| 维度 | 成功证据 |
|---|---|
| 全量回归第1轮 | 1514 passed、100 subtests passed、1 skipped、1 deselected、22 warnings，50.52秒 |
| 全量回归第2轮 | 同上，53.05秒 |
| 全量回归第3轮 | 同上，57.18秒 |
| 最终UI第1轮 | 独立会话round4，390×844：首页账号登录/错误密码、全部页面、模型加密保存/刷新、复核员只读、演示研究→自动报告→下载→逐项独立复核/发布→预测→8%/3%/5%观察、刷新保留、运营、取消、正式空间隔离，均通过 |
| 最终UI第2轮 | 独立会话round5，1440×1000，同一整套操作均通过 |
| 最终UI第3轮 | 独立会话round6，390×844，同一整套操作均通过；三轮均无pageerror、框架覆盖层或全页横向溢出 |
| 前序UI验证 | rounds1–3也完成上述完整操作；截图发现手机收益差需横向滚动，改为三项可见卡片后重复最终三轮 |
| 内置浏览器 | 556×665：首页演示→开始研究→七阶段/七次调用→自动报告→复核员批准/发布→预测与观察，页面证据收益8%/3%/5%，无溢出；仅一条来自IDE browserUse桥接EventEmitter的警告，无应用错误 |
| 安装及冷启动第1–3轮 | 仓库外`python -I`在无dev依赖venv运行wheel；资源与源码构建一致，spawn实际执行七次模型调用、生成报告，关闭测试自有HTTP对象再重建同端口服务，会话及report_id保持，独立复核/发布与5个百分点观察成功，正式账号未创建 |
| 正式入口 | 8780桌面/手机首页、演示研究执行/自动报告/刷新/退出通过；8765及8769旧入口链接至8780；正式库账号0、模型版本0、模型调用0，保留一个已取消历史任务 |
| 恢复及边界 | 自动报告意图持久化，成功但未登记结果重启补齐且版本唯一；阶段metadata白名单不写提示词；CSRF/Origin/越权/跨演示会话拒绝，研究员无自审权限，取消结果不生成报告 |
| 构建、lint及文档 | Vite293模块构建、sdist/wheel成功；全仓ruff、diff检查和32份文档本地链接/需求覆盖通过 |

首个全量执行为1513 passed、1 failed：旧`object.__new__`图测试夹具未设置callbacks字段，补齐正常构造已有的空callbacks后上述三轮全量均通过，未降低生产断言。正式入口验证脚本首次把Playwright的url属性当作方法，纠正后同脚本完整通过。内置浏览器第一次点击离屏批准按钮只滚动，重新取当前可见ref后成功打开弹窗。

实际记录：`runtime/logs/research-full-tests-{final,round2,round3}.log`、`research-browser-final.log`、`research-wheel-{check,round2,round3}.log`、`research-ready.log`；截图为`runtime/research-qa/round-{4,5,6}-evaluation.png`及`ready-{desktop,mobile,completed}.png`。安装包为`dist/research-flow-final/tradingagents-0.7.0-py3-none-any.whl`。

停止8772验收进程被自动审批拒绝（可能中断演示），已保留该进程；没有重试停止或采用间接绕过。最终服务另启8780，原8765/8769也保留。真实供应商授权与付费研究未调用，数据仍为明确合成内容；本次未commit/push。

## 10. 研究参数、来源与可操作配置验收（2026-10-25）

新版入口为 `http://127.0.0.1:8781/`。每个创建字段显示预置、配置或输入来源。研究模板新增/复制/编辑与版本保存已接入SQLite；研究参数、团队和本次降低的限额实际固定在任务中；持仓提供表格及JSON导入，持仓复核接收账户估值并绑定执行时留存的结构化行情。任务和报告可展开提交时输入。模板字段、允许选项、权限、错误位置和操作契约见[研究输入契约](../03-development/research-inputs.md)。

| 维度 | 已通过证据 |
|---|---|
| 针对性系统检查 | 45 passed，模板CAS/权限/重启/冻结输入、全部支持用途和资产、实际团队阶段与调用数、价格/集中度/做空阻断、HTTP错误不回显原始输入 |
| 最终完整回归第1轮 | `inputs-regression-round-4.txt`：1532 passed、100 subtests passed、1 skipped、1 deselected、22 warnings，61.91秒 |
| 最终完整回归第2轮 | `inputs-regression-round-5.txt`：同上，110.65秒 |
| 完整逐字段UI | 两组桌面/手机，共四轮，每轮新增/复制/编辑/刷新模板、所有字段和选项、模型/模板往返草稿、团队/限额、JSON文件导入、持仓增删、错误及焦点；实际执行一般/事件研究和账户持仓复核，共12份合成任务，目标仓位3%，全部通过 |
| 实际交付入口 | 8781在1440×1000、390×844、844×390实际开始研究、四次模型调用、固定输入、模型设置草稿往返、报告、刷新及退出通过；无pageerror/横向溢出；8765/8769链接到8781 |
| 用户记录保留 | 原数据库两个已有账号哈希及正式任务分母更新前后相同；未添加测试账号或密钥。测试数据均在隔离演示/QA空间 |
| 安装及重启第1、2轮 | 仓库外 `python -I` 运行site-packages安装包，两轮页面资源与交付构建相同；保存模板→实际四次合成模型调用→持仓3%估值→重建同端口HTTP服务→模板、会话、固定输入及报告保持→复核员批准/发布均通过 |
| 构建与静态检查 | Vite296模块，sdist/wheel构建成功；全仓ruff及diff空白检查通过 |

前序全量第1、2轮也分别1532通过。补充第3轮及单项复核暴露超时测试假设：子进程在2秒期限后才抵达首次调用预留，生产代码正确以LeaseLost拒绝并超时，测试却无条件访问第一个调用。修正测试以同时覆盖“没有调用”和“已调用但账单unknown”，继续保持2秒期限、8秒以内退出、禁止迟到文件写入，并新增超时后再次预留必须拒绝且账本不变的断言。生产超时与预算逻辑未放宽；之后上述第4、5轮完整通过。

内置浏览器出现“No URL is loaded”、`net::ERR_ABORTED`和点击后没有状态变化，完成有界恢复后改用现有Playwright做实际控件操作。原8780停止操作被自动审批拒绝，理由为可能影响已有入口且没有针对该PID的明确终止授权，已保留该进程；新版8781使用原数据库，无终止绕过。

记录为 `runtime/logs/inputs-{browser-final,browser-delivery,ready,regression-round-4,regression-round-5,wheel-round-1,wheel-round-2}.txt`；结果及桌面/手机截图为 `runtime/inputs-qa/`。安装包为 `dist/research-inputs-final/tradingagents-0.7.0-py3-none-any.whl`。真实付费供应商和外部行情未调用；可选AWS依赖缺失测试跳过，外部集成测试按既有配置排除。本次未commit/push。

## 11. 入门投资者路径与交付验证（2026-10-25）

当前入口为 **http://127.0.0.1:8782/**，使用原数据库和已有密码账号；旧本机服务保留。现状分析覆盖首次进入、创建、等待、阅读、可信度、回访、学习和专业能力，详细契约与结果见[入门投资者改进](../03-development/beginner-investor.md)。快速研究默认三个控件，完整参数仍可编辑；新增个人关注、核实笔记及报告只读概览，合成价格/缺失论据/未复核状态明确显示。

| 维度 | 实际通过证据 |
|---|---|
| 完整离线回归第1轮 | 1537 passed、100 subtests passed、1 skipped、1 deselected、22 warnings，85.05秒 |
| 完整离线回归第2轮 | 1537 passed、1 skipped、1 deselected、22 warnings，95.69秒 |
| 最终入门UI三轮 | 8810隔离库，1440×1000、390×844、844×390；快速三个控件、名称/期限/用途固定、设置往返草稿、真实报告与原文节选、合成/缺口说明、关注/笔记/重复添加/刷新/移除、指南搜索及专业切换全部通过 |
| 原字段配置两轮 | 8811新隔离库，桌面/手机；全部字段/选项、模板新增/复制/编辑/持久化、持仓表格/文件导入/估值、错误焦点、冻结团队/限额，实际六份合成任务及3%仓位计算通过 |
| 实际交付入口三轮 | 8782在相同三种尺寸完成上述入门操作，无pageerror或横向溢出；正式登录页仅只读检查，前端三份资源与构建一致 |
| 身份与数据真实性 | 五项新增系统测试：跨账号/工作空间、并发100个关注上限、移出批准范围后旧笔记、本人历史不被他人覆盖、禁止请求指定所有者；缺失段落无编造、价格异常不显示、损坏固定文件读取拒绝 |
| 账号实际操作 | 隔离正式QA账号保存笔记→退出→再登录保持；另一研究员账号和合成空间无法读取该笔记 |
| 安装与冷重启三轮 | 仓库外`-I`加载site-packages；七次离线模型实际执行并生成报告，随后两个独立进程在相同端口恢复真实cookie、报告、笔记及最近任务；账号/正式演示隔离和CSRF拒绝通过 |
| 用户数据保留 | 既有两账号、模型版本1、两加密密钥记录、三正式任务、40条调用账本，启动与三轮入口验收前后整行校验值一致；未向正式库加入测试账号或调用付费模型 |
| 构建与静态检查 | React/Vite、sdist/wheel成功；ruff、diff空白和34份维护文档链接/需求覆盖通过 |

结果为`.cache/beginner-{regression-1,regression-2,ui-delivery,inputs-delivery,ready,wheel-round-1-delivery,wheel-round-2-delivery,wheel-round-3-delivery,live-delivery-preserved}.log`。实际入口截图和JSON为`runtime/beginner-ready/`，逐字段JSON为`runtime/inputs-qa-beginner/input-rounds.json`，安装重启JSON为`runtime/beginner-wheel-delivery/round-{1,2,3}.json`。安装包位于`dist/beginner-delivery/`。

前序实际UI暴露演示按钮首屏不可见、完成报告入口过低及横屏侧栏不可滚动；修复后上述最终三轮及实际入口三轮均成功。内置浏览器先完成AAPL真实合成任务和关注操作，后出现连续导航/选择超时，经过有界恢复后用现有Playwright补验。验收脚本旧首页断言、缺少幂等头、静态资源路径及任务终态名称按真实协议修正；生产权限、质量和限额规则未放宽。

本次未请求真实供应商或外部行情，未做真实投资者访谈或投资有效性评估；AWS可选依赖缺失仍跳过，外部integration默认排除。本次没有commit/push或外部部署。

## 12. 内置选股、有界股票研究与真实复验（2026-10-25）

当前入口为 **http://127.0.0.1:8783/**，使用原数据库、账号和模型设置。此轮用户明确要求预置股票、USD/CNY和推荐基准，解决已创建真实研究失败的问题，并突出股票研究与买卖判断的核心价值。分析、来源覆盖、默认路线及实际边界见[股票研究改进](../03-development/stock-research-usability.md)。

| 检查 | 实际结果 |
|---|---|
| 内置目录 | 21,271条：美股12,885、A股5,576、港股2,810；源目录完整性校验、中文/英文/代码搜索、分页、港股人民币柜台、原币种及基准预置通过 |
| 有界股票路线 | 固定资料分析、多方、反方、风险综合四次模型调用；SDK重试0，每环节至多重试1次，最多8次；提交前验证预留预算，不增大费用上限 |
| 新增针对性检查 | 目录、授权、冻结配置、报价/显示分离、预留门禁、完成报告、网络/解析/截断失败、异常行情在模型前拒绝、调用账本和原文损坏拒读通过；专项及分层10 passed |
| 完整回归第1次 | 首次检查发现应用层直接导入yfinance，按分层规则迁移到dataflows；修正后执行下方两轮完整回归 |
| 最终完整回归第1轮 | `.cache/stock-regression-2.log`：1546 passed、100 subtests passed、1 skipped、1 deselected，72.04秒 |
| 最终完整回归第2轮 | `.cache/stock-regression-3.log`：同上，61.99秒 |
| 实际UI | 桌面1440×1000、手机390×844、横屏844×390；市场切换、茅台/腾讯/苹果搜索选择、原币种/推荐基准、显示USD/CNY、期限、问题、草稿往返、报告、关注/笔记/重载/移除均通过 |
| 完整字段与恢复 | 桌面/手机两轮全部模板配置、字段/选项、持仓/导入/估值通过；独立QA账号隔离与旧BudgetExceeded任务恢复验证原CNY报价修正为USD、显示CNY、当前日期及推荐8次调用，原失败输入保留 |
| 真实执行 | 原失败任务所属本人新任务`1028a6852ddc4d2b99ad7774b6eda3ae`，报告`def84885f05d4e378a17ac4f915252c6`；4次模型调用完成，预留2,000,000微美元，真实NVDA/USD、基准SPY及有日期USDCNY汇率；未下单 |
| 真实报告UI | 桌面/手机实际通过访问控件进入本人最近报告，确认210.96 USD、约1405.12 CNY、汇率日期、Underweight原文、理由/风险/条件、折叠原文及质量状态；只读临时凭据随后撤销 |
| 安装与重启 | 仓库外`python -I`确认新模块来自site-packages、页面资源一致、21,271条目录及分页搜索可用；合成示例实际7次调用生成报告，后续独立进程恢复同端口cookie、报告、笔记与个人记录；不会把安装合成验证称为真实行情证明 |
| 用户数据 | 原两账号/密码hash、两加密密钥、模型版本及全部旧任务/调用行hash保留，增加授权的恢复研究；原服务进程保留，新入口另启8783 |
| 构建与静态检查 | React/Vite构建、sdist/wheel、ruff、diff空白、本地文档链接与需求覆盖通过；运行依赖锁未变 |

真实首轮7次调用返回资料不足，原因是1200输出额度下当前模型返回空正文；系统正确未将其冒充Hold。恢复模板已有4096额度后4次调用收尾，原10,000,000微美元费用上限和密钥不变。首轮部分结果也完整留存，最终任务另建新版本。来源许可未声明，新闻条目为空，财务快照与模型结论尚未人工复核，因此真实报告是可读取草稿，质量仍阻断批准/发布；没有伪造许可或自动复核。此证据不证明预测准确率、投资胜率或收益优势。

最终记录：`runtime/stock-real-validation.json`、`runtime/stock-real-initial.json`、`runtime/stock-ready/ready-rounds.json`、`real-report-ui.json`及截图，`runtime/stock-account-qa/account-and-recovery.json`、`runtime/stock-qa/input-rounds.json`、`runtime/stock-wheel-delivery/round-{1,2,3}.json`；日志`.cache/stock-*`，安装包`dist/stock-research/`。Browser桥接前序连续超时后采用现有Playwright实际操作，此轮没有伪造浏览器成功，也没有停止原服务、commit/push或外部发布。

## 13. 全链文档同步、连接保存与仓库合并前验证（2026-10-25）

用户授权全面同步需求、方案、开发、测试、运营、运维及治理，推送最新本地代码并合并默认main。此次37份维护文档统一为PROD-DOC-2.0，原始拉取SHA和上游归档不改写；PRD与矩阵为21项FR/10项NFR，新增当前状态、快捷路线ADR和文档责任/来源/周期/陈旧清单。当前行为、历史验证与生产目标分别注明。

| 验证 | 本次新执行结果 |
|---|---|
| 现有模型连接/保存 | quick、deep各1次短连接测试均connected，保存当前相同配置为版本2；原密文记录和参数不变，新任务引用新revision，旧任务不回写 |
| 文档/编号清单 | scripts/check_docs.py：37份、本地链接和需求覆盖通过；37份均在文档控制登记，21FR/10NFR一致 |
| 全量回归第1次 | `.cache/docs-release-regression-1.log`：1546 passed、100 subtests、1 skipped、1 deselected，65.90秒 |
| 提交审查发现/修正 | allow_listed_stocks启用时，明确批准的非目录BTC-USD关注项被误标不可研究；新增回归先失败，修正为显式批准与目录授权的并集，移出显式批准后仍正确不可用 |
| 修正专项 | test_beginner_investor.py与test_guided_stock.py：15 passed，6.77秒 |
| 最终全量回归 | `.cache/docs-release-regression-2.log`：1547 passed、100 subtests、1 skipped、1 deselected，71.35秒 |
| 前端/开发接线 | Vite299模块构建；开发代理补research/instruments/watchlist/demo并指向8783，内置浏览器实际选苹果/买入问题→7次合成调用→自动报告→保存关注成功，无应用error/overflow |
| CI增量 | PR执行前端构建并检查提交bundle无漂移；clean-install smoke新增3页面和21,271条目录/原币种检查，运行依赖锁hash保持 |
| 发行验证 | 新sdist/wheel构建通过，独立安装环境在仓库外-I确认3页面、目录与原币种；managed help可用，包资源与源码构建一致 |
| 静态/内容检查 | ruff与git diff --check通过；私有runtime/.env/token/解密文件不在受跟踪集合；生成股票目录不包含实时价格或模型密钥 |

内置浏览器验证地址为`http://127.0.0.1:5173/web/`，直接运行前端源码和本机代理；报告价格100 USD明确为合成，不能归入真实研究证明。真实模型测试仅连接，原NVDA报告不重跑或改写。发行包仅本地验收，不上传官方release、不创建tag、不触发云部署；包0.7.0继续是来源值。原服务/账号/数据保留。

仓库推送、PR、远端CI与main合并使用实际Git/PR状态作为最终真相；本节是提交前证据，不预写“已合并”。已授权的合并按head SHA确认，保护规则/check失败不能绕过。可选AWS依赖未装仍跳过，网络integration仍按默认排除；无生产SLO、云灾备或金融胜率结论。日志为`.cache/docs-release-*`，本地构建为`dist/docs-release/`。
