# 本次工程验证记录

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
