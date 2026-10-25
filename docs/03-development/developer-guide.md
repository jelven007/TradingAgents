# 开发指南

状态：2026-10-25当前开发操作；面向工程，由工程责任角色依据pyproject、锁文件、CI和源码维护。命令、接口、打包或分层变化后及每次合并前复核。生产待建范围见[实施计划](implementation-plan.md)，历史验证不等于本次命令结果。

## 1. 环境与启动

Python ≥3.11，推荐3.13；macOS默认3.9不能运行本项目。所有命令从根目录执行：

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp config/env/local.env.example .env
tradingagents --help
```

先安装再 `python -m cli.main`；SDK示例为 `python examples/analyze.py`。真实分析需配置供应商凭据，默认测试不需要真实密钥。设置 .env 权限600，不把凭据写入代码或示例。

启动当前本机工作台：`python -m cli.main managed --templates config/examples/managed-templates.json serve --port 8783`。数据库/对象默认在runtime；首次创建管理员，已有安装保留原账号，模型在设置中测试/保存。只监听loopback，不能直接映射公网。完整操作见[工作台](web-workbench.md)。

团队复现建议使用uv 0.13.5与提交的锁文件：

```bash
uv sync --frozen --extra dev --python python3.13
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file requirements.lock --quiet
```

`uv.lock`是完整依赖解析，`requirements.lock`是由它导出的默认运行依赖，供Docker hash安装；Bedrock额外依赖需单独安装/验证。普通pip按pyproject范围安装是支持的开发入口，但不能视为冻结环境。具体版本及产物见[验证记录](../04-testing/validation-report.md)。

## 2. 代码职责

CLI只解析输入、选择配置并展示；graph负责编排、状态和恢复；agent只基于明示数据生成分析；数据工具通过router到vendor；模型客户端负责能力兼容。禁止agent直接调用yfinance，避免数据错误被当作金融事实。

`application/service.py`是授权与用例入口，`runs.py`选择完整或快捷graph，`guided_stock.py`固定四环节；真实行情适配器在`dataflows/guided_stock.py`，模型客户端由factory创建。`securities.py`读取包资源并按权限分页；`investor.py`只读固定正文/证据，不新增模型论据。认证、模型/研究配置、任务、报告、关注和评估存储在infrastructure。

前端修改`web/src/`；Python包内`src/tradingagents/web/`是必须提交的运行资源，禁止手改bundle。开发需要Node22，运行已安装包无需Node：

```bash
cd web
npm ci
npm run build
# 开发预览：先启动8783后npm run dev，接口由Vite代理到loopback服务。
```

构建后核对3个包资源与源码产物一致；代理必须包含research、instruments、watchlist和demo路径。证券目录用`scripts/build_stock_catalog.py`从源目录构建，只在需要更新目录时联网；旧缓存不能证明新目录日期，应先保留旧产物再使用新的缓存目录重取并核对完整性。

配置从 `deepcopy(DEFAULT_CONFIG)`开始，避免浅拷贝嵌套字典互相影响。每并发任务创建独立graph，不共享 `_checkpointer_ctx`。已有 `run_config`/ContextVar有助于配置隔离，但不替代任务、存储及实例隔离。

新vendor需注册工具能力、错误分类、时间窗口、明确fallback和来源，不增加用户未选择的隐藏fallback；新模型需验证structured output、tools、reasoning/max_tokens/temperature、endpoint和API key映射。

## 3. 开发流程与提交

从需求ID创建任务，描述边界、实现、迁移、验收与风险。小步提交，先明确接口与失败路径，必要时用离线替身复现后修复。保留许可证。分支使用`feature/<id>-description`或`fix/<id>-description`；本机代码积累在chore/production-foundation，推送/合并应先确认实际远端状态，不将历史“未提交”当作当前事实。

PR应写“何种输入以前如何、现在如何”，附需求ID、验证、兼容/迁移、回滚。架构变化新增ADR；数据库变更采用expand→migrate→contract，禁止与旧版本互不兼容的单步破坏性变更。

## 4. 本地门禁

```bash
make lint PYTHON=.venv/bin/python
make docs-check PYTHON=.venv/bin/python
make test PYTHON=.venv/bin/python
make test-system PYTHON=.venv/bin/python
make build PYTHON=.venv/bin/python
```

默认测试包含系统用例，常规验证通过后无需重复运行system；单独命令用于定位与开发。测试要验证业务不变量、异常与边界，避免镜像实现的断言。不因目录重排批量改提示词、格式或业务行为。

UI变更需实际桌面/手机/横屏验证选择、错误、报告和刷新；Python回归通过不能替代浏览器。真实模型测试与离线fixture分别记录，模型测试上限和费用预留不是完整研究能力验证。CI应构建前端并检查提交的bundle未漂移；包smoke必须从仓库外读取页面及证券目录。

## 5. 新增能力的完成定义

实现代码、类型/输入约束、最小必要测试、错误/取消/幂等路径、观测字段、文档和迁移说明齐备。供应商协议测试、真实模型质量与负载测试各自有独立证据。任何未实现目标在文档中保持待建，不能由目录、示例或离线替身代替。
