from copy import deepcopy

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


# DEFAULT_CONFIG already applies TRADINGAGENTS_* env-var overrides
# (llm_provider, deep_think_llm, quick_think_llm, backend_url, etc.),
# so users can switch models or endpoints purely via .env without
# editing this script. Override individual keys here only when you
# want a hard-coded value that should ignore the environment.
def main():
    config = deepcopy(DEFAULT_CONFIG)
    ta = TradingAgentsGraph(debug=True, config=config)
    _, decision = ta.propagate("NVDA", "2026-09-01")
    print(decision)


if __name__ == "__main__":
    main()
