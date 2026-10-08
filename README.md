# AI 即兴剧场

本地单人版互动叙事引擎。无需模型密钥即可使用确定性 Demo；DeepSeek 模式需要在页面设置中临时填写密钥，后端重启后会清除。OpenAI 选项目前待开发验证。

## Windows 本地启动

需要 Python 3.11+、Node.js/npm、PostgreSQL，以及 Windows PowerShell 5.1 或 PowerShell 7。默认数据库地址为 `postgresql+psycopg://theater:theater@localhost:5432/theater`；请先创建对应的本地用户与数据库，或在启动脚本所在的终端设置 `DATABASE_URL` 和 `MIGRATION_DATABASE_URL`。只写入 `backend/.env` 不会被 Alembic 迁移读取。

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

若使用非默认数据库，在同一 PowerShell 终端设置连接地址，再启动：

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/theater'
$env:MIGRATION_DATABASE_URL = $env:DATABASE_URL
pwsh -NoProfile -File .\scripts\start-local.ps1
```

使用 Windows PowerShell 5.1 时，将最后一行改为 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1`；执行策略覆盖只作用于这个新进程。

使用默认数据库时，直接运行最后一行。脚本会检查依赖和 8000/3000 端口、执行迁移，然后启动仅监听 `127.0.0.1:8000` 的 API 与 `http://localhost:3000` 页面。按 `Ctrl+C` 正常退出；若 Windows 提示 `Terminate batch job (Y/N)?`，输入 `Y`，脚本随后会停止它启动的后端进程。脚本不会启动 PostgreSQL、自动安装依赖或保存 API 密钥。

遇到启动失败，先看终端错误；后端启动日志保存在系统临时目录的 `ai-improv-api-<进程号>.err.log`。可运行 `pwsh -NoProfile -File .\scripts\test-start-local.ps1` 检查启动脚本的前置条件提示。
