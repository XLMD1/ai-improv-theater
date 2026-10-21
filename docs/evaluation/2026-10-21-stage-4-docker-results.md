# 2026-10-21 阶段四 Docker 实际构建补验

## 结论

用户已启动 Docker 并通知继续；此前“本轮不启动 Docker”的限制不再阻止本次已批准的独立验收。Docker 引擎可连接，构建上下文的实际 BuildKit 检查通过；应用镜像构建在下载官方基础镜像前因 Docker Hub 网络连接超时停止，尚未启动应用容器。阶段四仍未验收关闭。

本次没有修改应用代码或 Docker 定义，没有导入、重置或删除用户数据库、图片与存档。沿用 `codex/stage4-docker` 的 `b2c6e2f`，干净 `git archive` 展开至忽略目录 `runtime/stage4-docker-20261021/source`。测试项目名 `theater-stage4-test-20261021`，预留回环端口 18080，测试密码临时生成并包含 URL 保留字符，仅写入该隔离源码的忽略 `.env`，未打印或提交。

## 实际检查

| 项目 | 结果 |
| --- | --- |
| 引擎 | Docker Desktop 4.85.0；Engine 29.6.2，Linux/amd64，连接成功；开始时无运行容器与 Compose 项目 |
| 干净源码／配置 | 从提交导出；无本机 runtime、backend/.env 或三局私有样本；使用独立项目名，`compose config --quiet` 通过 |
| 首次应用构建 | 在镜像认证前失败：当前终端 PATH 无 docker-credential-desktop。仅在构建子进程加入已安装 Docker bin 路径后解决；未读取或修改凭据存储、系统 PATH |
| 再次应用构建 | 在基础镜像 metadata 阶段失败：访问 auth.docker.io:443 的匿名认证请求连接超时；未安装应用依赖，未创建应用容器 |
| 网络诊断 | Docker 引擎未配置 HTTP/HTTPS 代理及 registry mirrors；宿主机将 auth.docker.io 解析至 104.244.46.71，registry-1.docker.io 解析至 199.59.148.9。记录观察值，不将其认定为已证明的 DNS 根因；未改 DNS、Docker 全局设置或使用第三方镜像 |
| 实际构建上下文 | 用无外部基础镜像的 `FROM scratch` + `COPY .` 经 BuildKit 导出实际上下文，检查通过：canon、迁移、公开 Demo 图片、锁文件和部署入口均在；根 .env、runtime、三份历史草稿、.git、node_modules 不在。用合成哨兵确认排除规则后移除自建哨兵，保留原始干净源码 |
| 应用运行／恢复 | 未执行：镜像尚未构建，不能据 scratch 上下文检查推断 Nginx、API、数据库、SSE、三结局、卷持久化或浏览器恢复通过 |

原始构建日志和上下文导出留在忽略的 `runtime/stage4-docker-20261021/`，不提交数据库密码或实际凭据。scratch 检查没有启动容器，不需要访问 Docker Hub，不代表完整应用镜像已构建。之前[源码检查与待验收清单](2026-10-19-stage-4-docker-results.md)继续有效，历史 353 项后端、30 项前端及构建结果本次未重跑。

已请用户提供可用 Docker 网络入口或自行配置 Docker Desktop 网络；网络可用后继续基础镜像下载、完整构建和独立卷启动，再执行原容器验收清单。未付费调用任何模型，未推送或合并分支。
