# 阶段四：Docker Compose 与源码交付设计

日期：2026-10-19。状态：用户已于 2026-10-19 确认方案并要求直接实施；容器实现／验收状态另行记录。依据用户“优先docker，不要便携包了，方便别人通过下载源码和依赖的方式运行我的项目”。沿用阶段三已收尾的源码基线 `5453d12`，不重做游戏规则、图片流水线或前端视觉。

## 目标与使用流程

用户安装 Docker Engine 与 Compose v2（Windows 通常用 Docker Desktop），下载源码，复制公开的 `.env.example` 为 Git 忽略的根 `.env` 并设置本地数据库密码，再执行 `docker compose up --build -d`，浏览器访问 `http://localhost:8080`。依赖由镜像构建安装，宿主机无需单独安装 Python、Node.js 或 PostgreSQL。首次构建需网络，后续用已构建镜像启动 Demo 无需模型接口。

保留 README 中 Python／Node／PostgreSQL 直接安装及 `scripts/start-local.ps1` 方式。源码开发仍使用原 `backend/.env`，Docker 不读取或挂载该文件。没有 Windows 便携包、安装器、云部署、多用户或预发布镜像仓库工作。

## 最小架构（本设计的实现选择）

- `web`：多阶段构建，Node.js 22 执行 `npm ci` 与 Next 静态导出；构建时 `NEXT_PUBLIC_API_URL=/api`。运行镜像为官方 Nginx 稳定系列，提供 `out`，固定 `/`、`/create`、`/play?id=...`，查询参数保留。运行容器无需 Node。
- `api`：Python 3.12，安装现有后端 pyproject 依赖和源码。容器内仅一个 Uvicorn worker、内部监听 `0.0.0.0:8000`，不发布宿主机端口；原源码启动仍监听 `127.0.0.1`。私有容器网络作为新增运行边界，不扩大到局域网／公网。
- `db`：官方普通 PostgreSQL 18，不使用旧草稿中的 pgvector。与现有本机数据库完全独立，不挂载既有 pgdata、不导入现有用户库、不发布 5432。
- 只将 `web` 映射到 `127.0.0.1:${APP_PORT:-8080}:80`；`APP_PORT` 可改为未占用端口。容器间按 Compose 服务名访问，不用宿主机的 localhost。
- Nginx `/api/` 代理至 `api:8000/`，保留认证、幂等头和查询参数；关闭 SSE 缓冲与上游请求重试，`proxy_read_timeout` 为 1300 秒，覆盖现有最长 1200 秒图片任务。不能因代理重复转发收费写请求。浏览器使用同源 API，不增设通配 CORS。
- 镜像使用明确、经验证的稳定标签；PostgreSQL 固定 18 主版本，Python 固定 3.12、Node 固定 22。具体补丁／Nginx 标签在实施构建时核实并记录，不用 `latest`。

## 初始化、配置与持久化

根 `.env.example` 仅提供 `APP_PORT` 与本地数据库参数示例，无实际密钥。API 密钥继续通过游戏设置进入后端内存，不写 Compose、镜像、卷或浏览器存储。Docker 启动代码安全构建数据库 URL，处理密码中的 URL 保留字符，避免把密码放在命令参数或日志里；不修改原配置优先级。

Compose 等待 db 的 `pg_isready` 健康后启动 api；API 入口先执行现有 `alembic upgrade head`，成功后用 exec 启动单 worker，失败明确退出。API 健康后启动 web。不得用重建用户数据库或无界重试掩盖迁移失败。

独立命名卷保存数据库和 `RUNTIME_DIR=/app/runtime`；PostgreSQL 18 数据卷挂载 `/var/lib/postgresql`，遵循官方新版 PGDATA 目录。后端镜像需允许其运行用户写 runtime 卷。源码、内置 canon、迁移和 Demo 公开图片进入镜像；根／后端 `.env`、`.git`、node_modules、开发虚拟环境、runtime、现有用户图／数据库／日志及三份未追踪后端草稿排除在构建上下文外。

首次干净拉取仅提供内置 Demo 和空故事库；现有三局本地审核样本依赖忽略目录与本地数据库，不作为本次源码发布的预置数据，不制作样本导出／导入功能。用户可在自己的设置中填入密钥创建新故事，固定素材持久化。

正常操作提供 `up --build -d`、`ps`、`logs`、`stop`、`start` 与 `down`；普通停止／移除容器均保留卷。清空数据只作为明确标注的手动危险操作，绝不写入默认启动／升级路径。更新需拉取源码、重建镜像并增量迁移，不自动升级 PostgreSQL 主版本。浏览器端会话凭据绑定访问 origin，同一地址继续使用才能自动恢复。

## 文件边界与旧草稿

正式入口新增根 `compose.yaml`、`.dockerignore`、`.env.example`；部署文件放在 `deploy/docker/`，包括 API 与静态前端 Dockerfile、Nginx 配置及必要启动代码。范围只解决容器构建、代理、迁移和启停，不重构应用。

原主工作区未追踪 `docker-compose.yml` 是历史数据库草稿，保留原样、不暂存；正式 README 使用 `compose.yaml`，对存在旧草稿的开发目录可显式用 `docker compose -f compose.yaml ...`。三份未追踪后端草稿同样保留且排除，不将它们作为 Docker 实现依据。

## 验收与实施边界

1. 配置与构建：`docker compose -f compose.yaml config --quiet` 通过，使用干净源码实际构建镜像，入口文件与公开 Demo 资源齐全；检查镜像／上下文不含个人数据和密钥。
2. 新卷启动：独立测试项目名及独立卷启动到 healthy，自动迁移；默认只有回环网页端口，api／db 无宿主机映射，网页 `/api/health` 和固定路由可用。
3. 实际游玩：Demo 三结局、分支回放与长文本／图片读取通过同源代理，SSE 事件和幂等提交正常；按钮路径不触发真实模型调用。
4. 保留与恢复：停止、重建／重启后数据库会话与 runtime 哨兵文件保留；同 origin 浏览器当前节点和草稿恢复；API 重启清除内存密钥，不重发未知结果。
5. 失败边界：缺失配置、错误数据库连接、数据库未就绪、迁移失败、主机端口占用可诊断；迁移失败不会运行 API，代理不重试收费写请求。相关源码测试／typecheck／静态构建按改动执行。
6. 用全新临时 clone／archive 证明没有依赖当前忽略数据；与用户数据库和 3000／8000 预览隔离。删除测试卷仅限明确命名、可丢弃的测试项目，不操作用户卷。

检查结果进入阶段四开发日志及验收报告。已在用户目录发现 Docker Desktop 与 Compose CLI；用户明确要求本次不启动 Docker，先完成实现。当前仅执行无需 Engine 的配置检查及源码测试；实际镜像构建和容器启动前，阶段四不得标记验收通过。不会自动安装 Docker／WSL、修改 BIOS／防火墙或要求重启电脑。

## 已核实的官方依据

- [Compose 启动顺序与健康依赖](https://docs.docker.com/compose/how-tos/startup-order/)
- [Compose 服务网络与服务名](https://docs.docker.com/compose/how-tos/networking/)
- [Docker 端口发布与回环绑定](https://docs.docker.com/engine/network/port-publishing/)
- [PostgreSQL 官方镜像及 18 的数据目录](https://hub.docker.com/_/postgres)
- [Next.js 静态导出](https://nextjs.org/docs/app/guides/static-exports)

用户已确认默认 8080、三服务、独立持久化、Demo 起步、设置页密钥和源码路径保留，并授权生成计划后直接实施；无须逐步重复确认。
