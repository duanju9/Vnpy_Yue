# Auto: full sector sync -> sector_meta / sector_member (SQLite), monitor logs, validate.
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File run_sector_sync_full_auto.ps1

$ErrorActionPreference = 'Stop'
$Root = 'D:\Vnpy\Vnpy_Yue'
$MaxWaitHours = 6

Set-Location -LiteralPath $Root

$log = Join-Path $Root 'examples\miniqmt_research\data\sector_sync_full.log'
$err = Join-Path $Root 'examples\miniqmt_research\data\sector_sync_full.err.log'
$db  = Join-Path $Root 'examples\miniqmt_research\data\miniqmt.sqlite'

# 显式指向研究库 SQLite，避免与其它环境混淆（路径含空格由 Join-Path / LiteralPath 处理）
$env:MINIQMT_SQLITE_PATH = $db
$env:MINIQMT_USERDATA = 'D:\Program Files (x86)\QMT\迅投极速策略交易系统交易终端 华鑫证券QMT实盘\userdata_mini'
if ($env:MINIQMT_PG_URI) { Remove-Item Env:\MINIQMT_PG_URI -ErrorAction SilentlyContinue }

function Clear-LogFiles {
    param([string]$LogPath, [string]$ErrPath)
    for ($i = 0; $i -lt 60; $i++) {
        try {
            '' | Set-Content -LiteralPath $LogPath -Encoding utf8 -ErrorAction Stop
            '' | Set-Content -LiteralPath $ErrPath -Encoding utf8 -ErrorAction Stop
            return $true
        } catch {
            Write-Host "log locked, wait ($i/60) ..."
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

if (-not (Clear-LogFiles -LogPath $log -ErrPath $err)) {
    Write-Host "Stopping python jobs that match download_sector_members_to_db.py ..." -ForegroundColor Yellow
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -like '*download_sector_members_to_db*') } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
    if (-not (Clear-LogFiles -LogPath $log -ErrPath $err)) {
        throw "Cannot truncate log/err. Close apps locking: $log"
    }
}

Write-Host "=== sector full sync (auto) ===" -ForegroundColor Cyan
Write-Host "ROOT=$Root"
Write-Host "MINIQMT_SQLITE_PATH=$($env:MINIQMT_SQLITE_PATH)"
Write-Host "MINIQMT_USERDATA=$($env:MINIQMT_USERDATA)"
Write-Host "LOG=$log"
Write-Host "ERR=$err"
Write-Host ""

$procArgs = @(
    'examples/miniqmt_research/download_sector_members_to_db.py',
    '--include', 'all',
    '--sleep', '0.05'
)

$p = Start-Process -FilePath 'python' -ArgumentList $procArgs `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $log `
    -RedirectStandardError $err `
    -PassThru

if (-not $p) { throw 'Start-Process returned null' }
Write-Host "Started python PID=$($p.Id) (Hidden, redirected IO)" -ForegroundColor Green

$deadline = (Get-Date).AddHours($MaxWaitHours)
$lastShown = ''
$pollSec = 6
$doneOk = $false
$iter = 0
$lastHeartbeat = Get-Date

while ((Get-Date) -lt $deadline) {
    $iter++
    $alive = Get-Process -Id $p.Id -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $log) {
        $tail = @(Get-Content -LiteralPath $log -Tail 120 -ErrorAction SilentlyContinue)
        $prog = $tail | Where-Object { $_.StartsWith('[progress]') } | Select-Object -Last 1
        if ($prog -and ($prog -ne $lastShown)) {
            Write-Host ("[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $prog)
            $lastShown = $prog
            $lastHeartbeat = Get-Date
        }
        foreach ($line in $tail) {
            if ($line.StartsWith('[ok]')) {
                Write-Host "[done] log contains [ok]" -ForegroundColor Green
                $doneOk = $true
                break
            }
        }
    }
    if ($doneOk) { break }
    if (-not $alive) {
        Write-Host "[exit] process ended PID=$($p.Id)" -ForegroundColor Yellow
        break
    }
    if (((Get-Date) - $lastHeartbeat).TotalSeconds -ge 120) {
        $hb = if ($lastShown) { $lastShown } else { '(no [progress] yet)' }
        Write-Host ("[{0}] [watch] PID={1} still running; last progress: {2}" -f (Get-Date -Format 'HH:mm:ss'), $p.Id, $hb)
        $lastHeartbeat = Get-Date
    }
    Start-Sleep -Seconds $pollSec
}

if (-not $doneOk -and (Get-Date) -ge $deadline) {
    Write-Host "[timeout] after ${MaxWaitHours}h (child may still run PID=$($p.Id))" -ForegroundColor Red
}

if (Get-Process -Id $p.Id -ErrorAction SilentlyContinue) {
    Wait-Process -Id $p.Id -Timeout 300 -ErrorAction SilentlyContinue
}

try { $p.Refresh() } catch {}
$exitCode = $null
try { $exitCode = $p.ExitCode } catch {}

Write-Host ""
Write-Host "=== stderr scan (errors / warns) ===" -ForegroundColor Cyan
$errIssues = @()
if (Test-Path -LiteralPath $err) {
    $errIssues = @(Select-String -LiteralPath $err -Pattern '(?i)(traceback|error|exception|fatal|\[warn\])' -ErrorAction SilentlyContinue)
    if ($errIssues.Count -gt 0) {
        $errIssues | Select-Object -First 40 | ForEach-Object { Write-Host $_.Line }
        if ($errIssues.Count -gt 40) { Write-Host "(... $($errIssues.Count) matches, showing first 40)" }
    } else {
        Write-Host "(no error-pattern lines in full err file)" -ForegroundColor Green
    }
} else {
    Write-Host "(no err file)"
}

Write-Host ""
Write-Host "=== stderr tail (50) ===" -ForegroundColor Cyan
if (Test-Path -LiteralPath $err) {
    $eTail = @(Get-Content -LiteralPath $err -Tail 50 -ErrorAction SilentlyContinue)
    if ($eTail.Count -eq 0 -or (($eTail -join '').Trim().Length -eq 0)) {
        Write-Host "(empty stderr)" -ForegroundColor Green
    } else {
        $eTail | ForEach-Object { Write-Host $_ }
    }
} else {
    Write-Host "(no err file)"
}

Write-Host ""
Write-Host "=== stdout tail (30) ===" -ForegroundColor Cyan
if (Test-Path -LiteralPath $log) {
    Get-Content -LiteralPath $log -Tail 30 | ForEach-Object { Write-Host $_ }
}

Write-Host ""
Write-Host "=== SQLite check ===" -ForegroundColor Cyan
$pyPath = Join-Path $Root 'examples\miniqmt_research\data\_sector_count_check.py'
@'
import sqlite3
from pathlib import Path
import sys

def table_exists(c, name):
    r = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (name,)).fetchone()
    return r is not None

p = Path(sys.argv[1])
if not p.is_file():
    print("DB_MISSING", p)
    sys.exit(2)
con = sqlite3.connect(str(p))
cur = con.cursor()
for t in ("sector_meta", "sector_member", "stock_cn_name"):
    if not table_exists(cur, t):
        print(t, "TABLE_MISSING")
        continue
    try:
        n = cur.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
        print(t, n)
    except Exception as e:
        print(t, "ERROR", e)
# 机器人相关板块抽样（与概念选股文档一致）
kw = "%" + "\u673a\u5668\u4eba" + "%"
try:
    ns = cur.execute(
        "SELECT COUNT(*) FROM sector_meta WHERE sector_name LIKE ?", (kw,)
    ).fetchone()[0]
    nm = cur.execute(
        "SELECT COUNT(*) FROM sector_member WHERE sector_name LIKE ?", (kw,)
    ).fetchone()[0]
    nd = cur.execute("SELECT COUNT(DISTINCT code) FROM sector_member WHERE sector_name LIKE ?", (kw,)).fetchone()[0]
    print("robot_like_sector_meta", ns)
    print("robot_like_sector_member_rows", nm)
    print("robot_like_distinct_codes", nd)
except Exception as e:
    print("robot_like_CHECK", "ERROR", e)
con.close()
'@ | Set-Content -LiteralPath $pyPath -Encoding utf8
$dbCheckLines = @(& python $pyPath $db 2>&1)
$dbCheckLines | ForEach-Object { Write-Host $_ }
Remove-Item -LiteralPath $pyPath -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=== summary ===" -ForegroundColor Cyan
$okFound = $false
if (Test-Path -LiteralPath $log) {
    $okFound = [bool](Select-String -LiteralPath $log -SimpleMatch '[ok]' -ErrorAction SilentlyContinue)
}
if ($okFound) {
    Write-Host "STATUS: OK ([ok] in log)" -ForegroundColor Green
} else {
    Write-Host "STATUS: FAIL or incomplete (no [ok]); ExitCode=$exitCode" -ForegroundColor Red
}
Write-Host "LOG: $log"
Write-Host "ERR: $err"
Write-Host "DB:  $db"
Write-Host "Re-run: powershell -NoProfile -ExecutionPolicy Bypass -File `"$Root\examples\miniqmt_research\data\run_sector_sync_full_auto.ps1`""

$sumPath = Join-Path $Root 'examples\miniqmt_research\data\sector_run_auto_summary.txt'
$errTailTxt = ""
if (Test-Path -LiteralPath $err) {
    $errTailTxt = (Get-Content -LiteralPath $err -Raw -ErrorAction SilentlyContinue)
    if (-not $errTailTxt) { $errTailTxt = "(empty)" }
} else { $errTailTxt = "(no file)" }
$logTailTxt = ""
if (Test-Path -LiteralPath $log) {
    $logTailTxt = (Get-Content -LiteralPath $log -Tail 35 -ErrorAction SilentlyContinue | Out-String)
}
$dbTxt = $dbCheckLines -join "`n"
$statusLine = if ($okFound) { "OK: log contains [ok]. Sector sync finished." } else { "FAIL: no [ok] in log; check stderr and Python." }
$report = @"
========================================================================
  Sector full sync - auto summary (UTF-8)
========================================================================
Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
ROOT: $Root
MINIQMT_SQLITE_PATH: $($env:MINIQMT_SQLITE_PATH)
MINIQMT_USERDATA: $($env:MINIQMT_USERDATA)
Child PID: $($p.Id)  ExitCode: $exitCode

[stderr excerpt]
$errTailTxt

[stdout last 35 lines]
$logTailTxt

[SQLite row counts]
$dbTxt

[Verdict]
$statusLine
LOG: $log
ERR: $err
DB:  $db
========================================================================
"@
[System.IO.File]::WriteAllText($sumPath, $report, [System.Text.UTF8Encoding]::new($false))
Write-Host ""
Write-Host "Summary UTF-8 file: $sumPath" -ForegroundColor Green
