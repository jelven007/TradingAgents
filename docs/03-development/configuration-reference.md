# 配置、优先级与环境

状态：以下“当前配置”已由源码实现；预算、租户、API设置属于未来平台契约，不添加无效环境变量。

## 1. 入口差异与优先级

包导入时从当前工作目录查找 `.env`，然后加载 `.env.enterprise`，均不覆盖已有shell变量；`DEFAULT_CONFIG`在导入时建立，后续修改环境需调用 `build_default_config()`重新读取。SDK显式传入config优先，CLI另有flags/env/prefs交互规则，不能当作所有入口通用优先级。

CLI每个flag跳过其对应提问；受支持 `TRADINGAGENTS_*` 环境值跳过相应配置提问；剩余问题使用上次CLI偏好作为默认，最后使用内置默认。无TTY缺少必要答案会提前失败。嵌套SDK配置用deepcopy，vendor子字典由dataflows按一层合并。

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

## 5. 环境划分

local可交互、独立目录；test强制离线、临时路径；受控CLI试运行按操作者/实验隔离缓存、结果、记忆与checkpoint；未来staging/production经版本注册和secret manager设置。生产API的预算、身份、队列和数据库配置在具体实现时定义，不将设计参数冒充已生效配置。
