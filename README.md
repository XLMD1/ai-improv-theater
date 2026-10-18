# AI 即兴剧场

本地单人版互动叙事引擎。无需模型密钥即可使用确定性 Demo；DeepSeek 模式需要在页面设置中临时填写密钥，后端重启后会清除。OpenAI 选项目前待开发验证。

## Windows 本地启动

需要 Python 3.11+、Node.js/npm、PostgreSQL，以及 Windows PowerShell 5.1 或 PowerShell 7。将本地数据库连接地址写入 `backend/.env` 的 `DATABASE_URL`；该文件已加入 Git 忽略规则，不要提交其中的密码。Alembic 优先使用进程环境变量 `MIGRATION_DATABASE_URL`、其次 `DATABASE_URL`，未设置时读取 `backend/.env`。

首次安装依赖：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
cd ..\frontend
npm ci
cd ..
```

脚本优先使用 `backend/.venv`，也支持已有的项目根目录 `.venv`。

若使用非默认数据库，先把连接地址写入 `backend/.env` 的 `DATABASE_URL`，再运行启动命令：

```powershell
pwsh -NoProfile -File .\scripts\start-local.ps1
```

如果需要临时覆盖 `.env` 配置，可在启动脚本的同一个终端设置 `DATABASE_URL`；迁移使用不同数据库时再额外设置 `MIGRATION_DATABASE_URL`。

使用 Windows PowerShell 5.1 时，将最后一行改为 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1`；执行策略覆盖只作用于这个新进程。

使用默认数据库时，直接运行最后一行。脚本会检查依赖和 8000/3000 端口、执行迁移，然后启动仅监听 `127.0.0.1:8000` 的 API 与 `http://localhost:3000` 页面。按 `Ctrl+C` 正常退出；若 Windows 提示 `Terminate batch job (Y/N)?`，输入 `Y`，脚本随后会停止它启动的后端进程。脚本不会启动 PostgreSQL、自动安装依赖或保存 API 密钥。

遇到启动失败，先看终端错误；后端启动日志保存在系统临时目录的 `ai-improv-api-<进程号>.err.log`。可运行 `pwsh -NoProfile -File .\scripts\test-start-local.ps1` 检查启动脚本的前置条件提示。

## 本地无密钥样本

故事库提供已发布的古代、近现代、未来样本。点击“开始试玩”建立独立进度；调查、交流、出示、移动、结局按钮和回放无需 DeepSeek 或智谱密钥。自由文字输入仍需 DeepSeek 密钥。按用户保留试玩的要求，已批准 R1 故事及八图文件校验齐备的测试样本加入 `runtime/local-samples.json`，画面质量问题保留记录，阶段三最终范围与结果见下文收尾说明；目录尚未发布时不会显示样本入口。保留当前本地数据库与 `runtime/generated-images/`，勿将目录、故事、图片或会话凭据提交到 Git。此模式仍需启动本地服务。

## 阶段三运行与验收

当前首页是逐局保存的故事库。自定义故事流程为背景／年代 → 已校验简介确认 → 八张固定素材 → 调查舞台；在本地设置依次配置 DeepSeek 和智谱 CogView-4，OpenAI 仍禁用。密钥仅在后端内存，重启后须重填；已保存剧情和图片回放无需密钥。CogView-4 固定普通同步 0.06 CNY/次，八图 0.48 CNY，文字另按用量估算；未知结果须核账，恢复不会自动重发不确定的生成请求。

阶段三已于 2026-10-18 按用户确认的调整范围收尾，见[收尾记录](docs/evaluation/2026-10-18-stage-3-closeout.md)。核心流程、真实三年代技术路径和电脑端验收已有记录；手机实机测试未执行，自动配图质量仍有已知偏差，用户明确将两项作为非阻塞保留项。本地三个样本使用用户审核通过的 24 张图片；便携包和 OpenAI 文字支持仍属后续阶段。自动测试不替代人工质量评价。见[实施专题](docs/design/stage-3-completion.md)及[固定验收口径](docs/evaluation/stage-3-acceptance.md)。运行 `evals/run_stage3.py` 前，预览服务和运行器必须使用同一个独立 PostgreSQL `_test` 库；服务测试库指纹必须匹配，正常用户库不会提供该指纹。运行器只使用已在本地设置保存的内存密钥；不要通过命令参数传入 API Key。报告、冻结故事及测试会话凭据位于忽略的 `runtime/evals/`，不得提交这些本地数据。

## 阶段 1 规则评测

阶段 1 已提供严格调查协议、确定性裁决、可达性校验及增量版本迁移。当前界面继续使用 Demo；完整雾港调查样本已获用户批准并冻结为 1.0.0，阶段 1 已验收。见[剧情与证据材料](docs/design/mist-harbor-draft-review.md)及[批准版本实测](docs/evaluation/2026-10-10-stage-1-approved-results.md)。

安装后端测试依赖后，从根目录运行：

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -e './backend[test]'
.\backend\.venv\Scripts\python.exe evals/run_stage1.py --suite rules
```

已有根目录 .venv 时使用对应 Python。规则套件无需数据库或模型密钥。旧存档兼容套件需要已完成迁移的独立 PostgreSQL *_test 库，并在进程环境中设置 MIGRATION_DATABASE_URL 后运行：

```powershell
.\backend\.venv\Scripts\python.exe evals/run_stage1.py --suite legacy --database-url-env MIGRATION_DATABASE_URL
```

缺测试库、失败、错误、跳过或超时均保留固定分母并返回非零。JSON 报告位于 Git 忽略的 runtime/evals；这些结果证明规则与兼容性，不表示真实 AI 任务成功率。详细口径见[评测规范](docs/evaluation/task-success-baseline.md)。
