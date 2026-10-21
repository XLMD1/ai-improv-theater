# 2026-10-19 阶段四 Docker 实现与验证

2026-10-21 续验：用户已启动 Docker，最新引擎／构建检查及网络阻断见[补验记录](2026-10-21-stage-4-docker-results.md)。以下保留 2026-10-19 当日结论。

## 当日结论

用户已确认 Docker Compose／源码交付方案，并明确“已经安装 Docker，只是现在不打算启动运行，先完成实现”。本轮提供配置、镜像定义、迁移入口、HTTP 验证脚本及文档；没有启动 Docker Desktop、Engine 或容器，没有执行镜像拉取／构建。阶段四实际容器验收保持未完成。

实现分支 `codex/stage4-docker`，沿用阶段三 `5453d12`，设计基线 `db1198a`。阶段三收尾及手机／图片质量保留项不变；OpenAI 和多 Agent 未开启。

## 已实施

- `compose.yaml`：web／api／db，默认只有 `127.0.0.1:8080`；数据库和 API 不发布宿主机端口，健康依赖按 db → api → web；web 对 api 配置显式更新时联动重启，最低 Compose 2.17。
- 官方镜像定义：Python 3.12、Node 22 构建、Nginx 1.30.6 Alpine、普通 PostgreSQL 18.6 Alpine；实际镜像构建尚未执行，标签来源见下方官方链接。
- Docker 专用入口安全组装数据库 URL，先完成 Alembic，再 exec 单 worker Uvicorn；缺密码或迁移失败则退出，错误输出不包含迁移原始日志或密码。不修改源码模式的配置优先级。
- 静态导出构建使用 `/api`，Nginx 同源代理关闭 SSE 缓冲及上游重试，读取超时 1300 秒；运行时持久化至单独卷，PostgreSQL 18 卷根为 `/var/lib/postgresql`。
- 构建上下文按允许列表选择源码与公开资源，排除 `.env`、运行数据及历史未追踪草稿。初次源码只有公开 Demo，不包含本机三局私有样本。
- 可选 `scripts/test-docker.py` 只访问已运行的回环 HTTP 服务，创建两个 Demo 会话，验证三个结局、不可变回放、分支隔离、幂等、授权和完成后的 SSE 事件；不启动服务、不删除数据、不调用付费接口、不输出会话令牌。
- README 包含下载／安装／配置／构建／访问／更新／启停／故障排查，保留 Windows 源码直接安装路径。

## 本轮实际检查

| 检查 | 实际结果与边界 |
| --- | --- |
| 新启动入口和验证脚本 | RED：入口缺失时 5 项失败；脚本缺失且连接测试库后 6 项失败。实现后合并 11/11 通过，无跳过；最终配置修正后复跑仍 11/11，通过耗时 1.58 秒 |
| 独立 PostgreSQL 测试库 | 新建本机 PostgreSQL 18.4 测试集群，回环端口 25440，`stage4_regression_test`；七次增量迁移至 head，通过 `alembic check`，无新增 schema 差异。不是容器 PostgreSQL 实测 |
| 完整后端 | 首轮 352 通过／1 失败；原有 10ms 耗时差断言实测为 15ms，同时在运行前端构建。该文件单独复测 9/9 通过；完整串行复测 353/353 通过，13 条既有依赖弃用警告，用时 137.81 秒；未修改原有超时逻辑或放宽断言 |
| 前端 | 30/30、`npm run typecheck` 通过；同盘隔离目录的 `/api` 生产构建成功导出 `/`、`/create`、`/play` |
| Compose 5.3.1 | 不访问 Engine 的 `config --quiet` 通过；实际解析缺失密码拒绝、特殊字符与单引号、18080 端口覆盖、回环绑定、无 api/db 端口、18 版卷目录与健康依赖通过 |
| 原生 API 前缀 | 通过真实应用挂载 `/api` 的 TestClient 测试三个 Demo 结局、回放、幂等、授权与已完成 SSE；没有测试 Nginx、真实流式延迟或容器网络 |
| 文档／审查 | 9 份更改文档的本地链接与 `git diff --check` 通过；1 位独立 AI 审查者完成只读源码审查，发现 1 项重要问题、无严重或次要问题：后端重建可能令 Nginx 保留旧 IP。已加入 web 的依赖重启配置，实际 Compose 解析先检查失败后通过；运行时重建效果仍待容器实测 |

历史启动用的 25439 测试服务当前未运行，最初迁移尝试连接超时，测试尚未开始；后续改用上述新建测试集群，未重置用户库。首次隔离生产构建因 Windows 跨盘 node_modules 链接解析失败；改为同盘隔离目录后通过，未修改前端实现。Compose 的规范化输出会转义 `$`，以 `config --environment` 的实际输入值及规范化输出共同核对，未打印密码。

源码检查费用为 0 次模型调用。本轮未新增真实模型费用、质量评价或手机验收。源码测试产生的数据库、日志和报告均留在忽略目录，不打包进镜像。新建测试集群与用户旧服务／数据互不复用，结束后已仅停止本轮 25440 原生测试集群，文件保留。初始原生集群启动助手曾因捕获子进程输出超时，后续独立核实服务器已就绪才创建测试库；助手随测试集群停止后退出，不影响测试结论。

审查未扩展至云部署／TLS／多用户、样本导出导入或自动备份，均不在已批准范围内；也未检查实际凭据和 `.env` 内容，防止泄密。配置检查和源码审查只能证明联动重启声明已生效解析，不能证明容器网络中的实际恢复。

## 后续容器验收（本轮未执行）

以下是待执行步骤，不是通过记录。待用户选择启动 Docker 后，在干净 clone／archive 内操作，使用单独项目名 `theater-stage4-test`、空卷和未占用的 18080 端口；不要连接原用户数据库或使用日常项目卷。

1. 复制 `.env.example` 为根 `.env`，设置测试数据库密码和 `APP_PORT=18080`。用 `docker compose -p theater-stage4-test -f compose.yaml config --quiet` 验证；从干净源码执行 `up --build -d`，检查构建上下文、公开 Demo 文件和迁移结果。
2. 用同一 `-p theater-stage4-test -f compose.yaml` 执行 `ps`，确认三服务 healthy，并核对只有回环网页端口。检查 `/`、`/create`、`/play?id=...`、公开图片及 `/api/health`。
3. 安装了后端开发依赖的主机可执行 `python scripts/test-docker.py --base-url http://localhost:18080`，并在浏览器完成 Demo 分支、回放和 SSE；另检查长任务流式事件、图片读取、查询参数与幂等头确实通过 Nginx。
4. 在浏览器保留当前节点和草稿，并在容器 runtime 写入可识别的测试哨兵。对该独立项目执行 stop/start、down/up 和重建，单独更新后端并确认其容器 IP 变化后，验证网页 API 连接恢复且幂等请求不重复提交；验证会话、节点、草稿及哨兵保留；API 重启应清除内存密钥。不要在日志／报告中保存实际密钥或会话令牌。
5. 验证缺失配置、错误数据库连接、数据库未就绪、迁移失败、端口冲突的实际退出／提示及无静默重置；独立记录通过数、失败和未执行项。
6. 只停止本次命名测试项目并保留卷；后续如需清理测试卷，应先核实准确项目名。不得清理用户已有卷或本地故事数据。

上述容器门槛通过前不勾选阶段四。自动测试和配置解析不能替代实际构建、持久化及浏览器恢复证据。

## 官方依据

- [Docker Compose 健康依赖](https://docs.docker.com/compose/how-tos/startup-order/)
- [Compose 环境变量与单引号](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)
- [PostgreSQL 官方镜像和 18 数据目录](https://hub.docker.com/_/postgres)
- [Nginx 官方镜像](https://hub.docker.com/_/nginx)
- [Node 官方镜像](https://hub.docker.com/_/node)、[Python 官方镜像](https://hub.docker.com/_/python)
