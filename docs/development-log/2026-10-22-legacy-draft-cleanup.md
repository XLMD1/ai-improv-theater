# 清理未使用的历史草稿

日期：2026-10-22。用户了解四份未跟踪草稿的用途后明确要求“清理”，本次授权替代此前对这四份文件的保留要求。

## 清理范围

- `backend/app/generators.py`：旧单次生成／多 Agent／Demo 生成框架；部分依赖接口已不存在，多 Agent 已取消。
- `backend/app/llm.py`：旧通用模型和 embedding 客户端，使用已过时的配置字段。
- `backend/app/memory.py`：旧向量记忆检索原型，依赖当前未提供的 Memory 模型。
- `docker-compose.yml`：仅启动 pgvector/PostgreSQL 16 的旧开发数据库配置。

这四份文件在清理前均为本地未跟踪文件，删除不会形成受跟踪文件的删除 diff。当前模型调用、调查规则、祖先上下文与 `compose.yaml` 继续由正式模块负责。同步更新 AGENTS.md、开发计划与扩展计划中的当前保留说明；各阶段当时确实保留草稿的历史验收记录保留。

## 实际验证

- 核对四个目标的仓库路径与未跟踪状态；正式代码中没有旧模块导入或旧生成／记忆接口调用。删除后四个目标均不存在，`git ls-files` 对这些路径返回空。
- `app.main`、`app.jobs`、`app.story_creation`、`app.investigation_jobs`、`app.image_tasks` 均可导入；验证期间禁止数据库连接，没有访问用户数据库。
- 从 `backend/` 运行 `pytest tests/test_provider_execution.py tests/test_docker_entrypoint.py -q -p no:cacheprovider`，**10 passed，2.94 秒**，模型调用及迁移进程均模拟。
- 67 份文档的 311 个本地链接均有效，`git diff --check` 通过。

本次仅清理未使用原型并更新说明，未执行完整回归、真实模型调用或 Docker 实机验收；此前的验收记录保留其原日期和范围。
