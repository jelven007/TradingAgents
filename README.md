# TradingAgents 生产系统工程基线

基于 [jelven007/TradingAgents](https://github.com/jelven007/TradingAgents) 的多智能体金融研究框架，建立可持续开发的代码组织和全生命周期文档。最新拉取基线：`main` / `v0.7.0` / `e8f5503e9b86d5c2710b0c76b1f686703968c9df`，拉取日期为 2026-10-23。

**当前主路径是股票研究与买卖决策辅助。** 内置21,271条美股、A股和港股证券资料，按名称/代码选股；原始币种自动确定，预置美元/人民币显示及市场推荐基准。用户选择股票与问题，默认路线整理真实资料、比较多空观点并给出评级、依据、风险与重新评估条件，含重试最多8次模型调用。密码账号、复核、个人关注、完整参数、模板/模型配置、预算、评估及CLI继续可用。详见[股票研究改进与真实复验](docs/03-development/stock-research-usability.md)和[验证记录](docs/04-testing/validation-report.md)。

本机当前入口为 **http://127.0.0.1:8783/**，使用原数据库、已有密码账号和模型设置。点击“体验演示”可直接练习；真实研究使用已有账号登录。选择“开始了解公司”，搜索并点击股票、选择想了解的问题，系统完成研究并生成报告。行情和模型不足时返回“资料不足，暂不判断”，不会虚构价格或替换为合成数据；失败任务可使用推荐配置重新研究，旧记录保留。真实NVDA复验已通过4次模型调用生成完整草稿；模型观点、来源许可与人工复核状态分别展示，不承诺收益，也不执行交易。

## 项目如何工作

股票快捷研究先留存真实行情、公司、新闻、基准及所需汇率，随后固定执行资料分析、多方、反方、风险综合四个模型环节。完整专业路线仍可显式选择：四类分析师读取行情、基本面、新闻和情绪，多空及风险研究员辩论，最后形成评级。

这里的 Trader 和 Portfolio Manager 是研究角色。回测评估独立决策的收益与基准超额收益，没有持仓演化、资金账本或成交仿真。

## 本地开始

需要 Python ≥3.11；建议使用 Python 3.13。以下命令在仓库根目录执行：

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp config/env/local.env.example .env
# 编辑 .env：设置所选模型供应商的密钥与模型
tradingagents --help
tradingagents
```

安装后可用 `python -m cli.main`，或执行 `python examples/analyze.py`。源码采用 `src/` 布局，需先安装包；单独克隆后直接运行源码模块不再是支持的启动方式。

启动浏览器工作台（安装包已包含页面资源，运行时无需Node）：

```bash
python -m cli.main managed \
  --templates config/examples/managed-templates.json serve --port 8783
```

打开首页创建首次管理员或使用已有账号，亦可先体验演示；在设置中逐层测试真实模型并保存。股票资料和推荐参数已内置，快捷路线最多8次调用；展开完整参数可查看字段来源或切换专业路线。详见[新建研究输入](docs/03-development/research-inputs.md)及[工作台手册](docs/03-development/web-workbench.md)。

已有uv的团队可用 `uv sync --frozen --extra dev --python python3.13`复现依赖；仓库包含 `uv.lock` 和导出的 `requirements.lock`，容器按运行依赖的版本和hash安装。

完全无交互运行需要同时指定 CLI 参数和配置变量：

```bash
export TRADINGAGENTS_LLM_PROVIDER=openai
export TRADINGAGENTS_QUICK_THINK_LLM=gpt-6-luna
export TRADINGAGENTS_DEEP_THINK_LLM=gpt-6-sol
export TRADINGAGENTS_OUTPUT_LANGUAGE=中文
export TRADINGAGENTS_MAX_DEBATE_ROUNDS=1
export TRADINGAGENTS_MAX_RISK_ROUNDS=1
export TRADINGAGENTS_NO_UPDATE_CHECK=1
tradingagents --ticker NVDA --date 2026-10-16 --analysts market,news --save --no-show --checkpoint
```

模型名来自拉取版本的默认配置，实际可用性取决于供应商账户。详见[配置参考](docs/03-development/configuration-reference.md)。

```python
from copy import deepcopy
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

config = deepcopy(DEFAULT_CONFIG)
graph = TradingAgentsGraph(config=config)
state, rating = graph.propagate("NVDA", "2026-10-16")
graph.save_reports(state, "NVDA")
```

## 工程目录

```text
src/
  tradingagents/        # 分析、编排、数据、模型、记忆、回测、报告
  cli/                  # 已安装的命令行入口；保留 cli 导入兼容
tests/
  unit/                 # 模块与适配器隔离测试
  system/               # 离线完整流程、恢复、回测、无交互运行
  architecture/         # 分层、提示词、国际化、版本规则
config/env/             # 本地、企业、受控试运行环境模板
deploy/docker/          # 容器与 Compose
examples/               # SDK 调用示例
scripts/                # 工程检查
docs/                   # 需求 → 方案 → 开发 → 测试 → 运营 → 运维
```

目录职责及后续扩展约束见[目录迁移说明](docs/03-development/directory-migration.md)。运行数据默认位于 `~/.tradingagents`，禁止放入源码或提交到版本库。

## 检查与容器

```bash
make check PYTHON=.venv/bin/python
docker compose --project-directory . --env-file .env -f deploy/docker/compose.yaml build
docker compose --project-directory . --env-file .env -f deploy/docker/compose.yaml run --rm tradingagents
```

`make check` 执行 lint、文档引用检查、默认离线测试及打包；外部集成测试默认排除。Compose 是单机 CLI 运行模板。[验证记录](docs/04-testing/validation-report.md)说明本次实际完成的检查及限制，[部署手册](docs/06-runbooks/deployment.md)说明部署边界。

## 研发入口与来源

- [产品需求及验收标准](docs/01-requirements/product-requirements.md)
- [生产系统方案](docs/02-architecture/system-design.md)
- [开发任务与阶段门禁](docs/03-development/implementation-plan.md)
- [需求追踪矩阵](docs/01-requirements/traceability.md)
- [原始 README](docs/upstream/README.md)、[上游变更日志](CHANGELOG.md)

保留上游 Apache-2.0 [许可证](LICENSE)和版权声明。论文来源：[TradingAgents: Multi-Agents LLM Financial Trading Framework](https://arxiv.org/abs/2412.20138)。版本号0.7.0保留上游来源，仓库交付/合并以Git与PR记录为准，不能当作上游官方发行。当前事实和全部文档的维护路径见[当前状态](docs/00-overview/current-state.md)及[文档控制](docs/07-governance/document-control.md)；自有发行tag、云部署和生产签署另行处理。
