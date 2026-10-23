# 部署与受控运行手册

状态：本节提供**现有单机CLI部署命令**；后续API/worker生产部署按目标要求另行实现。当前Compose不包含数据库、API、队列或监控。

## 1. 本地与容器前置

从仓库根目录运行；Python≥3.11，Docker可用，已批准的模型与数据凭据、来源授权和运行数据目录准备好。模板不含有效凭据：

```bash
cp config/env/pilot.env.example .env
chmod 600 .env
# 编辑 .env，填写组织允许的模型凭据和配置
docker compose --project-directory . --env-file .env -f deploy/docker/compose.yaml build
docker compose --project-directory . --env-file .env -f deploy/docker/compose.yaml run --rm tradingagents --help
```

构建使用 `requirements.lock` 固定运行依赖和hash，然后安装项目。基础Python镜像目前仍为版本标签，生产发布前应锁镜像摘要并登记构建系统版本；这份模板不声称位级可重复构建。

默认将 `~/.tradingagents`容器目录持久化到命名volume，保存日志/报告、cache、memory与checkpoint。`.env`通过运行时env_file传入，不复制到最终镜像，runtime使用appuser。

## 2. 无交互任务

pilot模板已设置provider、model、语言和辩论深度；每次调用需补齐ticker、date、analysts、save/show。先从少量批准标的开始：

```bash
docker compose --project-directory . --env-file .env -f deploy/docker/compose.yaml run --rm tradingagents \
  --ticker NVDA --date 2026-10-16 --analysts market,news --save --no-show --checkpoint
```

不要对同一实验同时启动多份CLI进程。按操作者/实验指定独立存储，防止ticker/date记忆去重互相影响。宿主机bind mount通过TRADINGAGENTS_DATA_DIR指定，目录须可被容器appuser写入；检查uid/gid权限，不默认chmod777。

本地Ollama候选模板：

```bash
docker compose --project-directory . --env-file .env -f deploy/docker/compose.yaml --profile ollama up -d ollama
docker compose --project-directory . --env-file .env -f deploy/docker/compose.yaml --profile ollama exec ollama ollama pull <approved-model>
docker compose --project-directory . --env-file .env -f deploy/docker/compose.yaml --profile ollama run --rm tradingagents-ollama
```

该模式需将quick/deep模型设置成已拉取模型名；当前ollama镜像为latest，受控发布需锁定具体版本/摘要。Compose启动服务不证明模型已就绪。

## 3. 构建与发布检查

检查lint、文档、默认离线测试、sdist/wheel、仓库外CLI与package资源；镜像检查appuser、help、最终层无源码/密钥、存储权限和退出行为。真实分析属于有成本外部验证，需按批准样本执行，当前工程验证不代替它。

保留代码SHA、依赖锁hash、镜像digest、配置版本、环境、运行者和检查结果。包仍为0.7.0来源版本，发布自有产物前制定独立版本；禁止把此分支作为原始官方wheel发布。

## 4. 未来服务部署要求（待建）

公司内网入口/OIDC、独立API与worker、托管PostgreSQL/队列/对象存储、secret manager、指标日志、备份；dev/test/staging/prod独立凭据与数据。先迁移schema，再灰度服务，数据库用expand/contract保持旧版本兼容。禁止SQLite共享盘承担集群状态。

api readiness只检查必要内部依赖；worker收到停机信号停止领取新任务，保存状态或释放租约，等待有上限。部署失败先停止扩大流量，回滚应用与配置，不盲目回滚已变更的数据结构；详见[变更管理](../07-governance/change-release-management.md)。
