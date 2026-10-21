# 2026-10-21 阶段四 Docker 实际验收与收尾

## 结论和范围

阶段四已于 2026-10-21 按已确认的 Docker／源码交付范围完成实际验收，原设计六组门槛均通过。使用提交 `b2c6e2f` 的干净 `git archive`（之后的 `2289b18` 仅更新文档），独立项目 `theater-stage4-test-20261021`、新建数据卷与回环网页端口 18080；没有导入、重置或删除用户数据库、图片和存档。

本次验证包含实际官方镜像下载、前后端镜像构建、自动迁移、Nginx 同源访问、Demo 三结局、存档和素材卷恢复、浏览器页面恢复及失败边界。未重新付费生成自定义故事／图片；不新增模型质量、手机、OpenAI 或多 Agent 验收结论。Windows 便携包已取消，源码直接安装方式保留。阶段三的视觉失败和手机未测限制原样保留。

## 环境与证据

- Docker Desktop 4.85.0，Engine 29.6.2，Linux/amd64，Compose 5.3.1。
- 实际镜像：Python 3.12.15、PostgreSQL 18.6、Nginx 1.30.6；Node 22 仅构建静态页面，运行中的 web 镜像不存在 Node。
- 构建内实际安装 FastAPI 0.156.8、Uvicorn 0.54.0、SQLAlchemy 2.1.5、Pydantic 2.14.1、psycopg 3.3.6、Pillow 12.3.0；Next.js 15.5.27，`npm ci` 使用仓库锁文件。
- 测试密码临时生成并包含 URL 保留字符，仅留在隔离源码的忽略 `.env`，API 通过实际 TCP 数据库连接完成迁移；未打印或提交密码。供应商设置的清除测试使用无效占位密钥，不提交生成请求。
- 日志、报告、上下文导出、浏览器截图和测试会话凭据保存在原工作区忽略目录 `runtime/stage4-docker-20261021/`，不随源码分发。私有凭据文件不得公开。

## 六组实际验收门槛

| 组 | 结果 | 实际证据 |
| --- | --- | --- |
| 1．配置、构建及 Nginx | 通过 | 独立 `.env` 的 `compose config --quiet`；官方 Python／Node／Nginx 镜像下载并成功构建 api／web；最终按 README 再执行 `up --build -d --wait`。容器内 `nginx -t` 通过 |
| 2．新卷启动、迁移与网络 | 通过 | 从新命名卷启动，db → api → web 三服务 healthy，Alembic head 为 `0007_stage3_assets_budget`。只有 web 发布 `127.0.0.1:18080`，api／db 无宿主机端口；`/`、`/create`、`/play?id=...`、Demo WebP、`/api/health` 均正常。API 为 UID 10001，PID1 为 Uvicorn，无镜像内 .env |
| 3．游玩、回放与代理 | 通过 | 初次及最终两次 HTTP smoke 均完成 e1/e2/e3、8 个已保存节点、兄弟分支隔离、不可变回放、幂等重放、跨会话授权和已完成 SSE；每次账本均不变。Edge 通过真实按钮进入旧档案室，线索 1。相同生产 web 镜像的独立上游夹具另验证认证／幂等头、查询参数、路径前缀、流式事件和大响应，详见下方边界 |
| 4．持久化、重建与浏览器恢复 | 通过 | stop/start 以及 down/up 后，保存节点完整 JSON 相同，旧幂等键返回同一 run，runtime 哨兵 SHA-256 不变；内存占位密钥清除。Edge 刷新及关闭测试标签重开，仍为旧档案室／线索 1／原未发送草稿。API 单独重建且地址由 172.19.0.3 改为 172.19.0.4 时，原 web 容器自动重启并恢复代理，db 容器不变 |
| 5．失败边界 | 通过 | 五个独立故障场景见下表；均未重置数据或启动迁移失败的 API，恢复正常配置后原存档可读取 |
| 6．干净源码与上下文隔离 | 通过 | git archive 不含本地 runtime／私有三局样本／backend/.env；实际 BuildKit scratch 导出包含 canon、迁移、锁文件、公开图片和入口，根 .env、runtime、三份未追踪草稿、.git、node_modules 被排除；合成哨兵使用后已移除。首次网页仅提供公开 Demo 与空故事库 |

六组是已确认设计中的门槛，不是模型任务成功率。两次重复 smoke 不作为独立故事质量样本，不与历史源码测试计数相加。

## 失败边界实测

| 场景 | 注入与观察 |
| --- | --- |
| 缺少密码 | 独立 `compose run --rm --no-deps -e POSTGRES_PASSWORD= api` 返回 2，提示缺失配置，没有启动迁移或 Uvicorn |
| 数据库连接失败 | 同一独立项目将测试 API 的 POSTGRES_PORT 改为 1，返回 1，仅有安全迁移失败提示，未启动 API |
| 迁移失败 | 只读挂载抛错的测试 migration env 到一次性 API 容器，返回 1，未启动 Uvicorn；未改正式镜像或现有迁移 |
| 数据库不健康 | 独立 Compose override 将 db 健康检查设为 false，实际 up 失败且 API 未进入 running；移除 override 后正常 healthy，原卷及存档仍保留 |
| 端口冲突 | 一次性 web 尝试占用已由测试项目使用的 18080，明确返回非零绑定错误；仅清理带本轮标签的临时容器，主测试项目继续可用 |

这些属于容器故障注入，不是真实供应商失败或模型调用成功率。

## SSE、长文本及浏览器证据边界

同一个正式 web 镜像在单独临时网络连接测试上游，发送间隔 1.5 秒的两个 SSE 事件。实测首条为 0.031 秒、末条为 1.531 秒，证明本次代理未将首条缓冲到结束；2,000,120 字节文本响应的 SHA-256 一致。POST 的 Authorization、Idempotency-Key、`after=17`／含空格查询值及 body 完整到达上游，仅观察到一次调用。临时容器／网络已清理。此处是代理夹具测试，与真实应用的 Demo SSE 记录分开，不等同于重新执行 1200 秒收费图片任务。

浏览器为真实 Edge，由自动化操作，无本轮新增人工审核者。截图 `docker-browser-restore.png` 可见旧档案室、线索 1 和“Docker 恢复验收 1021…”的未发送草稿。完成了页面刷新、测试标签关闭重开及容器重建组合；没有关闭用户全部 Edge 窗口或重启 Windows。阶段三原有完整浏览器退出记录不改写为本轮结果。

## 费用、耗时、审查与清理

- 本轮数据库 `llm_calls` 数为 0，未付费调用模型；DeepSeek／智谱真实创建沿用前阶段记录。
- API 依赖安装构建层 43.1 秒，Next 生产构建层 13.6 秒；这些是单次层耗时，不是端到端均值或性能承诺。
- 代码沿用已完成的 1 位独立 AI 只读审查；其唯一 Important 问题为 API 重建后 Nginx 旧地址，已在本轮强制地址改变场景实际验证依赖重启修复。没有新委派第二次代码审查；本轮后续只有验收和文档改动。
- 本轮没有重跑全部 Windows 源码 pytest／前端测试；2026-10-19 的后端 353/353、前端 30/30、typecheck 和源静态构建按[历史报告](2026-10-19-stage-4-docker-results.md)保留。Docker 内生产构建和本轮 HTTP／故障／恢复结果独立记录。
- 验收结束仅停止本次测试项目，两个命名卷保留；临时代理、端口冲突和 IP 占位容器已清理，Docker Desktop 保持运行。未推送、合并或清理原用户数据。

## 本次遇到的问题及解决

1. 本机 Docker pipe 在沙箱内不可访问；正常权限连接成功，未修改引擎安全设置。
2. 首次构建缺少 docker-credential-desktop PATH；仅为子进程补充已安装 Docker bin，未读取或更改凭据存储。
3. 初始直连 Docker Hub 匿名认证超时；用户配置代理后，其 host.docker.internal 在 Windows 侧无法解析。确认本地代理可访问认证服务后，用户改用 127.0.0.1；构建客户端仍需代理环境变量，故仅为本次构建子进程设置 HTTP_PROXY／HTTPS_PROXY／NO_PROXY 后完整构建成功。未改 DNS、仓库镜像地址或 Docker 全局配置。
4. Windows 测试助手最初以 GBK 解码 Docker 的 UTF-8 状态输出失败；改用 UTF-8 后重查通过。该助手错误没有改动应用代码；实际 smoke 已单独通过。
5. 首次普通 API 重建复用了原 IP，虽证明 web 重启仍不足以验证旧地址问题；使用带本轮标签的临时占位容器保留旧地址，再单独更新 API，确认新 IP 和代理恢复。临时占位已删除。

## 使用与复现

普通运行按 [README](../../README.md) 的 Docker 步骤；需要 Docker 和可访问依赖源的网络，宿主机无需安装应用的 Python／Node／PostgreSQL。验收助手使用宿主机 Python 不构成运行依赖。

开发者在干净源码、单独项目名／测试端口和独立卷中，可执行：

```powershell
docker compose -p theater-stage4-test -f compose.yaml up --build -d --wait
python scripts/test-docker.py --base-url http://localhost:18080
docker compose -p theater-stage4-test -f compose.yaml stop
```

其中测试 `.env` 须设置独立密码及 APP_PORT=18080；HTTP 脚本需要后端开发依赖。其余故障／恢复按[已确认设计](../superpowers/specs/2026-10-19-stage4-docker-design.md)逐项复核。不要删除卷或公开私有凭据报告。
