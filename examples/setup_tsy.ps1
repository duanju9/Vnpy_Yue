# 一键安装依赖并提示配置 .env（不写入任何密钥）
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "已创建 .env，请用记事本打开本目录下的 .env，填写 TSY_TOKEN=你的56位key 后保存。"
    exit 1
}

$raw = Get-Content ".env" -Raw
if ($raw -notmatch "TSY_TOKEN\s*=\s*\S{50,}") {
    Write-Host ".env 中 TSY_TOKEN 未填写或长度不足，请编辑 examples\.env 后重试。"
    exit 1
}

python -m pip install -q -r requirements-tsy.txt
python tsy_xiaodefa_client.py
