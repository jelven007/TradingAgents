# ADR-0002：源码独立与导入兼容

- 日期：2026-10-23
- 状态：本次已实施；验证结果见[验证记录](../../04-testing/validation-report.md)
- 关联：FR-015、NFR-007
- 维护：工程责任角色面向开发/发布读者，2026-10-25复核；路径或打包规则变化时更新。

## 背景

原始根目录同时包含 `tradingagents/`、`cli/`、部署、截图和示例。根目录Python导入可以掩盖未打包模块或资源缺失，不适合长期生产工程开发。

## 决策

迁移包到 `src/tradingagents/` 和 `src/cli/`，通过setuptools从src发现包，console script仍为 `cli.main:app`。部署进入 `deploy/docker/`，环境模板进入 `config/env/`，示例进入 `examples/`，上游说明与截图进入 `docs/upstream/`、`docs/assets/upstream/`。测试按unit、system、architecture分组。

保留已有import路径，避免全仓重写业务代码。接受 `cli` 通用包名暂存的兼容性代价；未来独立API路径位于 `tradingagents.interfaces`，CLI改名需另一次兼容迁移。

## 后果与验证

源码运行先安装 `pip install -e ".[dev]"`；不添加sys.path补丁或根目录重复包。所有基于 `__file__` 的测试路径和发布版本读取须同步修改，架构扫描必须断言数据目录非空。

wheel安装必须从仓库外验证import、CLI help、welcome、logo、中文页面和证券目录；默认离线测试保持覆盖。原迁移时未推送是历史事实，当前提交/合并状态以Git/PR为准。
