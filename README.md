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

## 阶段 1 规则评测

阶段 1 已提供严格调查协议、确定性裁决、可达性校验及增量版本迁移。当前界面继续使用 Demo；完整雾港调查样本保持 draft，审定内容见[剧情与证据材料](docs/design/mist-harbor-draft-review.md)。

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
