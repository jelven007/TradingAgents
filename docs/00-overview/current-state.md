# 当前实现与证据入口

核对日期：2026-10-25；读者为产品、工程、QA和运维，工程责任角色维护。功能/路由/部署变化和每次合并前复核；超过30天或代码变化未同步时标记陈旧。本文件只汇总当前事实，需求编号、接口字段和运行命令分别链接唯一来源，不复制完整定义。

## 能力与限制

| 领域 | 当前事实 | 唯一详细说明 |
|---|---|---|
| 产品 | 股票研究辅助：选股票/问题，读结论、理由、反方、风险和条件 | [PRD](../01-requirements/product-requirements.md)、[工作台](../03-development/web-workbench.md) |
| 股票选择 | 安装包内21,271条美股/A股/港股源目录，名称/代码/市场分页 | [股票契约](../03-development/stock-research-usability.md) |
| 执行 | 工作台默认四环节、含重试最多8次；专业API默认完整图 | [ADR-0004](../02-architecture/adr/0004-guided-stock-research.md) |
| 来源 | 真实OHLCV/公司/新闻/基准/FX留存，币种及日期核对，缺口可见 | [数据治理](../02-architecture/model-and-data-governance.md) |
| 结果 | 完整/资料不足、质量、复核三种状态分开；固定hash校验 | [业务流程](../01-requirements/domain-workflows.md) |
| 本机用户 | 密码账号、CSRF、角色、模型/模板版本、本人关注和笔记 | [安全设计](../02-architecture/security-model.md) |
| 运维 | loopback单机SQLite与spawn worker，预算/租约/备份及冷重启 | [部署](../06-runbooks/deployment.md)、[恢复](../06-runbooks/backup-recovery.md) |
| 生产 | OIDC、云DB/队列/对象、完整许可、SLO、集群、长期质量仍待建 | [验收](../04-testing/acceptance-checklist.md)、[风险](../07-governance/risk-register.md) |

## 当前可定位的验证

真实NVDA最终研究使用4次模型调用生成complete草稿，保留USD报价与有日期CNY换算；来源许可未知、新闻缺口与人工论据仍待核验，因此不是可自动发布或下单的结果。单样本证明当前连接和预算内收尾，不证明金融胜率。原账号、密钥和历史记录保留；本机授权连接测试成功后保存新模型revision，旧任务仍引用原版本。

历史工程验证、三屏UI、逐字段两轮、真实报告UI与安装/重启在[验证记录](../04-testing/validation-report.md)分日期记录。每次交付仍须运行新命令，不能用旧“passed”代替当前证据；远端CI、提交和main合并以实际仓库SHA/PR为准。

## 查找路径

投资者从[工作台手册](../03-development/web-workbench.md)开始；开发从[开发指南](../03-development/developer-guide.md)和[配置](../03-development/configuration-reference.md)开始；问题处置从[故障手册](../06-runbooks/incident-response.md)开始；治理与历史辨认从[文档控制](../07-governance/document-control.md)开始。

当前本机入口约定为`http://127.0.0.1:8783/`，已有账号登录；地址是实例信息，仓库不会携带数据库/密码/密钥。包版本0.7.0保留上游来源，此轮仓库交付不创建官方发行tag或云服务。
