# 2026-10-19 Docker 与源码交付实现

用户取消 Windows 便携包，确认 web／api／普通 PostgreSQL 三服务、默认回环 8080、独立持久化、Demo 起步、设置页内存密钥及保留源码直接安装路径。已按[已确认设计](../superpowers/specs/2026-10-19-stage4-docker-design.md)和[分步计划](../superpowers/plans/2026-10-19-stage4-docker-implementation.md)在 `codex/stage4-docker` 顺序实现，不改游戏逻辑与供应商默认配置。

新增 Compose、两份镜像定义、Nginx 同源代理、迁移优先入口、允许列表构建上下文、HTTP Demo 验证脚本及行为测试。根 `.env.example` 调整为容器专用公开示例；源码模式继续读取 `backend/.env`，README 保留原安装方式。未追踪历史草稿与个人数据库／图片／凭据均未纳入交付。

用户说明 Docker 已安装，但要求本次不启动运行。已在用户目录找到 Docker Desktop 的 Compose 5.3.1，仅运行不访问 Engine 的配置解析。后端测试另建本机独立测试集群，未使用用户数据库。阶段四仍待真实容器构建、启动、代理、卷持久化与浏览器恢复验收。

测试和故障原始计数、环境限制及待验收清单集中记录在[本轮验证结果](../evaluation/2026-10-19-stage-4-docker-results.md)。不将源码 TestClient 或静态构建写成容器验收通过，也不新增真实模型费用或手机测试结论。
