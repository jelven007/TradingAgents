# 配置、优先级与环境

状态：2026-10-25当前配置参考，面向工程/管理员，工程责任角色依据DEFAULT_CONFIG、领域DTO和存储实现维护，配置字段或版本规则变化时及合并前复核。SDK/CLI、本机模板和浏览器版本化设置分别说明，不添加无效环境变量。

## 1. 入口差异与优先级

包导入时从当前工作目录查找 `.env`，然后加载 `.env.enterprise`，均不覆盖已有shell变量；`DEFAULT_CONFIG`在导入时建立，后续修改环境需调用 `build_default_config()`重新读取。SDK显式传入config优先，CLI另有flags/env/prefs交互规则，不能当作所有入口通用优先级。

CLI每个flag跳过其对应提问；受支持 `TRADINGAGENTS_*` 环境值跳过相应配置提问；剩余问题使用上次CLI偏好作为默认，最后使用内置默认。无TTY缺少必要答案会提前失败。嵌套SDK配置用deepcopy，vendor子字典由dataflows按一层合并。

本机服务启动读取可信`--templates` JSON，与DEFAULT_CONFIG合并；当前研究模板版本覆盖可公开编辑的默认值/允许范围/限额，当前模型版本覆盖两层provider/model/endpoint，提交options只可降低限额并选择允许项。TaskStore最终固定SDK重试0、输出token上限及实现指纹。旧任务读取冻结模型版本，不随“保存设置”回写；有变更的评估计划需新实验。

## 2. 当前环境变量

| 配置 / 变量 | 默认 / 说明 |
|---|---|
| `TRADINGAGENTS_LLM_PROVIDER` | openai；具体provider注册见factory |
| `TRADINGAGENTS_QUICK_THINK_LLM` / `DEEP_THINK_LLM` | gpt-6-luna / gpt-6-sol；从源码记录，账户可用性需验证 |
| `TRADINGAGENTS_QUICK_THINK_PROVIDER` / `DEEP_THINK_PROVIDER` | 空时继承主provider；覆盖层需同时指定相应model |
| `TRADINGAGENTS_LLM_BACKEND_URL` | 空时provider默认；层独立URL使用 `TRADINGAGENTS_QUICK_THINK_BACKEND_URL` / `DEEP_THINK_BACKEND_URL` |
| `TRADINGAGENTS_OUTPUT_LANGUAGE` | English；可设中文，内部辩论部分仍用英语 |
| `TRADINGAGENTS_MAX_DEBATE_ROUNDS` / `MAX_RISK_ROUNDS` | 各1 |
| `TRADINGAGENTS_MAX_TOOL_ROUNDS` | 20；需满足 `2*rounds+2 < max_recur_limit`，递归上限默认100仅config设置 |
| `TRADINGAGENTS_CHECKPOINT_ENABLED` | false；CLI `--checkpoint/--no-checkpoint`显式覆盖 |
| `TRADINGAGENTS_LLM_MAX_RETRIES` | None：SDK默认；数字限制每次SDK重试，不是任务总预算 |
| `TRADINGAGENTS_MAX_TOKENS` / `TEMPERATURE` | None；供应商支持情况不同，不能保证确定性 |
| `TRADINGAGENTS_OPENAI_REASONING_EFFORT` / `GOOGLE_THINKING_LEVEL` / `ANTHROPIC_EFFORT` | None，交由provider默认；支持值按模型能力校验 |
| `TRADINGAGENTS_RESULTS_DIR` | `~/.tradingagents/logs` |
| `TRADINGAGENTS_CACHE_DIR` | `~/.tradingagents/cache` |
| `TRADINGAGENTS_MEMORY_LOG_PATH` | `~/.tradingagents/memory/trading_memory.md` |
| `TRADINGAGENTS_BENCHMARK_TICKER` | 空时按交易所后缀选择区域基准 |
| `TRADINGAGENTS_NO_UPDATE_CHECK` | 设1关闭启动检查；无TTY本就不检查 |
| `TRADINGAGENTS_DATA_DIR` | 仅Compose解释的宿主机挂载路径，不是Python配置键 |
| `SEC_EDGAR_USER_AGENT` | 用本单位联系人替换默认，SEC要求可联系身份 |

完整映射及默认值以[default_config.py](../../src/tradingagents/default_config.py)为准；prefix表中短名称均应加 `TRADINGAGENTS_`。布尔接受 true/1/yes/on 或 false/0/no/off，非法布尔/数字启动即报错。

## 3. 凭据与供应商

常用密钥：OPENAI_API_KEY、GOOGLE_API_KEY、ANTHROPIC_API_KEY；其他支持项见[本地模板](../../config/env/local.env.example)。FRED、Alpha Vantage、TypeSafe等按选用工具单独需要凭据；SEC无需key但需User-Agent。Azure使用[企业模板](../../config/env/enterprise.env.example)，Bedrock需安装 `[bedrock]` extra并指定AWS地区/凭据。

ChatGPT订阅登录是上游支持的个人研究模式，生产服务优先使用组织授权API或托管模型。Ollama默认 `http://localhost:11434/v1`，远端可设OLLAMA_BASE_URL；自定义兼容服务使用openai_compatible与backend_url，生产入口不允许用户任意修改端点。

## 4. 仅SDK config支持的重要设置

`data_vendors`按类别、`tool_vendors`按工具覆盖，tool优先；显式链如 `"sec_edgar,yfinance"`只在链内fallback。`holding_period_days`默认5交易日，`benchmark_map`区域映射；`news_article_limit`等控制数据量，`memory_log_max_entries`只修剪已resolved记录。不存在自动加载YAML配置的实现。

2026-10-24迭代1新增可选 `research_mandate` 字典：ticker、analysis_date、prediction_horizon_trading_days、benchmark、quote_currency、valid_until为必填项，asset_type默认为stock，purpose默认为general_research。契约会进入分析上下文、状态日志及Markdown/HTML报告，并将holding_period_days和benchmark_ticker设置为契约值。调用propagate的标的/日期/资产必须与契约一致；跨日期网格需为每个单元建立契约，不可复用一个固定日期契约。

该契约只支持daily，拒绝intraday/cutoff等未实现字段；不会宣称拥有交易所盘中时点精度。期限按交易日描述，valid_until是日历日期，二者不自动互换。未提供契约的旧SDK/CLI继续使用既有配置。PortfolioContext同时拒绝重复标的、非有限数值、负成本价、未知字段；负数量仍表示空头，负现金并不被擅自解释成非法账户。

## 5. 环境划分

local可交互、独立runtime目录；test强制离线临时路径；受控CLI按实验隔离；未来staging/production由组织注册和secret manager提供。生产队列/OIDC配置尚未实现，不将设计参数冒充生效变量。

## 6. 本机模板、路线和密钥

| 设置 | 来源与默认 | 约束 |
|---|---|---|
| `research_policy.allow_listed_stocks` | 可信文件默认false，示例daily为true | 公共研究模板不能扩大目录授权 |
| `approved_tickers`、`source_licenses` | 可信文件策略/许可；公开模板可管理批准代码 | 许可unknown不自动通过，禁止伪造许可标签 |
| `options.execution_mode` | API缺省full，股票工作台缺省guided_stock | portfolio_review/crypto用完整路线 |
| `options.stock_question` | understand/buy/hold/sell | 股票意图，不自动生成账户估值 |
| `options.display_currency` | USD或CNY，UI默认USD | 原始报价由股票决定，FX失败保留原价 |
| 推荐benchmark | 美股SPY、A股000300.SS、港股^HSI | 可修改，固定入任务 |
| `TaskLimits` | 默认80次/1800秒/4096tokens/10,000,000微美元 | 示例daily40次/900秒，快捷UI8次；预算需容纳8次500,000预留 |
| `settings/models` | 版本化quick/deep provider/model/base_url/api_version | expected_version冲突409；普通研究员不能写 |
| `api_key` / `clear_api_key` | 密码字段，只接受写入，不回显 | 空值且目的地址相同保留；地址变化不携带旧密钥 |

浏览器连接测试每层只发1次、最多64输出tokens、15秒进程等待；测试不会保存，成功后再保存配置。数据库model_revisions保留公共版本、model_credentials保留密文，旁置`*.model-key`只由本机受控文件持有。备份恢复不复制解密文件，需重新配置密钥。所有私有runtime/.env/token不提交Git。设置版本2是在本机用户授权测试后保存的实例状态，不是仓库默认密钥或配置。
