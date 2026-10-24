# 备份、恢复与灾备演练

状态：2026-10-24，已有managed本地备份/恢复并完成离线演练，操作见[本地手册](../03-development/managed-research.md)，结果见[迭代记录](../03-development/iteration-log.md)。尚未执行真实生产数据或云灾备演练。NFR-005的RPO24小时/RTO4小时及服务化15分钟/1小时仍为待测目标。

## 1. 数据分类

必须保留：决策记忆、report/manifest、任务/attempt状态、配置与prompt版本、审计、实验结果、许可允许的证据快照。可重建缓存与临时文件不是核心备份目标。SQLite checkpoint影响中断恢复；缺失时可能只能新attempt从头运行，应明确恢复等级。

凭据单独由secret manager保护；不要把 `.env` 或ChatGPT个人登录文件混入共享备份。备份加密、最小访问权限、离开原故障域，保留恢复密钥及授权流程。

## 2. 单机流程

托管入口使用 `tradingagents managed backup <新目录>` 与 `restore <备份目录> <外部保存的backup_sha256> <新目录>`。SQLite backup API形成一致事务快照，复制已接受运行/报告引用的hash对象；同时保留任务/调用、复核、访问审计、控制、对账和实验/预测/观察。不会复制未接受attempt、可重建缓存或旧SDK独立memory；后者按下述旧CLI流程另备份。

恢复先核验backup manifest/全部对象及SQLite/任务输入/复核链/评估hash，在新目录重定位副本路径后启用；原库不动，副本queued/running全部取消，旧token撤销，unknown费用保留，不自动外部调用。新凭据和明确的新任务由本地运营者创建。备份hash应保存到独立可信位置，SQLite触发器/hash不能替代云WORM、加密、隔离故障域或保留策略。

以下为旧SDK/CLI文件memory/checkpoint的人工流程，不能与managed恢复命令混用：

1. 暂停新任务并等待当前任务结束；确认没有进程写memory、SQLite或报告。不得把活跃SQLite数据库简单cp当作一致性备份。
2. 记录代码SHA、依赖锁、配置（脱敏）、数据路径、备份时刻和最后完成任务。复制logs/reports、memory及需要恢复的checkpoint；运行中必须使用SQLite backup API或一致性快照，不能只复制.db遗漏WAL。
3. 生成文件清单、尺寸/hash；保存到受控加密备份位置，核验文件可读，检查保留期限与来源许可。
4. 在独立工作目录恢复，配置独立RESULTS/CACHE/MEMORY路径，先只读解析memory和report，再以离线/批准小样本验证checkpoint及报告。
5. 比对条目数、pending/resolved、评级、report引用、最后完成时间；差异解释后由责任人确认恢复，才切换运行路径。

备份位置、调度、加密和个人责任尚需落地；演练使用隔离fixture，没有修改用户原有运行数据。

## 3. 未来服务化流程

PostgreSQL使用基础备份+WAL/PITR，记录可恢复时间；对象存储采用版本和生命周期策略。数据库指针与对象在一致时间范围核对，未提交孤立对象不当作报告。队列重建可以从任务/outbox真相恢复，不依赖消息永不丢。

恢复到隔离环境，禁止自动外部模型调用；核验task/attempt/report/audit/config数量和引用hash、租约、费用账本、权限与RLS。运行中的任务在新环境必须重新判定租约/fencing，不能让旧worker继续提交。恢复后分批重新投递outbox，幂等核验accepted结果唯一。

## 4. 演练验收

记录事件/备份时间、最后可恢复事务、启动恢复时间、可服务时间，计算实际RPO和RTO；验证至少一个completed、pending、failed和checkpoint中断样本，跨租户授权、报告及证据完整。每月或重要架构变更后演练，失败需行动项。

恢复验收不仅是“数据库启动成功”，还包括业务记录/权限/对象一致性。清理旧环境、销毁临时密钥和确认数据保留政策在切换后完成。
