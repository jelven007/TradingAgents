# 目录迁移与扩展规则

状态：迁移已实施，2026-10-23。本次调整物理组织、路径检查与工程入口，算法模块及既有Python导入路径保留。

## 1. 迁移映射

| 原位置 | 现位置 | 原因 |
|---|---|---|
| `tradingagents/` | [src/tradingagents](../../src/tradingagents/) | 安装与源码隔离，模块发现可验证 |
| `cli/` | [src/cli](../../src/cli/) | 保留console script与import兼容 |
| `main.py` | [examples/analyze.py](../../examples/analyze.py) | 示例不承担生产入口；加main guard |
| `Dockerfile`、`docker-compose.yml` | [deploy/docker](../../deploy/docker/) | 部署文件集中维护 |
| `.env.example`、`.env.enterprise.example` | [config/env](../../config/env/) | 环境模板集中；实际.env留根目录并忽略 |
| `assets/` | [docs/assets/upstream](../assets/upstream/) | 上游截图属于说明材料 |
| 原README | [docs/upstream/README.md](../upstream/README.md) | 保留来源，根README建立中文工程入口 |
| 根tests单层文件 | [unit](../../tests/unit/)、[system](../../tests/system/)、[architecture](../../tests/architecture/) | 区分模块、完整工作流、架构约束 |

`tests/conftest.py`统一保留离线、密钥与文件隔离。系统目录的测试由collection hook补充 `system` marker，上游原有 `unit` marker保留；默认测试仍包含离线系统测试。网络测试仍需显式 `-m integration`，不会因为放在unit目录就自动执行网络。

## 2. 同步修改

setuptools添加 `where=["src"]`；国际化和分层测试调整repo root/src定位，分层检查增加非空断言，避免目录移动后“扫描零文件也通过”。版本测试与release工作流读取新路径。CLI welcome与logo仍作为package data进入wheel。

Docker builder从根context安装包，runtime只复制已安装venv，源码、文档及.env不进入最终层。Compose必须带 `--project-directory .`，否则相对build/env路径无法保证与根目录一致；标准命令见[部署手册](../06-runbooks/deployment.md)。

## 3. 扩展原则

保持模块化单体：`agents/`表达研究角色，`graph/`表达编排，`dataflows/`集中数据和vendor依赖，`llm_clients/`集中模型兼容，`memory/`集中历史决策，reporting/backtest分别负责展示与评分。禁止增加无边界的 `common/` 或 `utils/` 来绕过职责。

实现服务时新增 `interfaces/api/`、`application/`、`domain/`、`infrastructure/`，只在有可运行实现时创建。不能把现有模块重命名为domain就宣称完成依赖倒置。订单/成交另立领域与任务，不能混入评分回测。

运行数据不得位于src或Git；本地默认 `~/.tradingagents`，受控环境通过配置指定独立路径。Python工具环境 `.venv/`、`.bootstrap/`、`.tools/`、`.cache/`均忽略。

## 4. 上游同步与回退

origin保留用户指定 `jelven007/TradingAgents`，本地开发分支 `chore/production-foundation`。每次同步先 `git fetch origin`，记录SHA并在隔离分支重演迁移；新文件通常出现在上游旧路径，合并时需按映射放入src，不能直接pull覆盖已有开发。

回退必须在独立checkout验证原始SHA，备份本地未提交工作；不要通过 `git reset --hard` 丢弃本分支修改。格式化、全量重命名与业务算法升级分别提交，后续版本采用独立发布策略。
