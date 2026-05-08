# 从仓库根目录启动，自动 headless，避免终端卡在「欢迎/邮箱」导致端口不起
# 用法: powershell -ExecutionPolicy Bypass -File examples/chan_web/run.ps1
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
$env:STREAMLIT_SERVER_HEADLESS = "true"
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"
python -m streamlit run (Join-Path $PSScriptRoot "app.py")
