# Full auto: sector sync (hidden + logs) -> DB check -> robot union CSV screen -> picks report
# Run: powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "...\run_robot_sync_and_screen_auto.ps1"

$ErrorActionPreference = 'Stop'
$Root = 'D:\Vnpy\Vnpy_Yue'
Set-Location -LiteralPath $Root

$sectorScript = Join-Path $PSScriptRoot 'run_sector_sync_full_auto.ps1'
$log = Join-Path $Root 'examples\miniqmt_research\data\sector_sync_full.log'
$dailyDir = Join-Path $Root 'examples\miniqmt_research\daily_picks'
$dateStr = Get-Date -Format 'yyyyMMdd'
$csvOut = Join-Path $dailyDir "robot_union_${dateStr}.csv"
$finalReport = Join-Path $dailyDir "picks_robot_${dateStr}.txt"
$latestCsv = Join-Path $dailyDir 'latest_screen.csv'
$latestPicks = Join-Path $dailyDir 'latest_picks_robot.txt'

# UTF-16 code units for 机器人 (avoid non-ASCII in .ps1 source on some hosts)
$kwRobot = -join @([char]0x673A, [char]0x5668, [char]0x4EBA)

Write-Host "========== robot: sector sync + screen + picks ==========" -ForegroundColor Cyan
Write-Host "ROOT=$Root"

if (-not (Test-Path -LiteralPath $sectorScript)) {
    throw "Missing sector script: $sectorScript"
}

& $sectorScript
if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
    Write-Host "[warn] sector script exit code: $LASTEXITCODE" -ForegroundColor Yellow
}

$okFound = $false
if (Test-Path -LiteralPath $log) {
    $okFound = [bool](Select-String -LiteralPath $log -SimpleMatch '[ok]' -ErrorAction SilentlyContinue)
}
if (-not $okFound) {
    $msg = '[FAIL] sector sync: no [ok] in log. See: ' + $log
    [System.IO.File]::WriteAllText($finalReport, $msg, [System.Text.UTF8Encoding]::new($false))
    Write-Host $msg -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== robot union CSV screen -> daily_picks ===" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $dailyDir | Out-Null
$pyScr = Join-Path $Root 'examples\miniqmt_research\concept_sector_screen_csv.py'
$pyScreen = @(
    $pyScr,
    '--union-substring',
    $kwRobot,
    '--out',
    $csvOut
)
$p2 = Start-Process -FilePath 'python' -ArgumentList $pyScreen `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -Wait -PassThru
if (-not $p2 -or ($p2.ExitCode -ne 0)) {
    $ec = if ($p2) { $p2.ExitCode } else { 'null' }
    Write-Host "concept_sector_screen_csv.py failed ExitCode=$ec" -ForegroundColor Red
    exit 2
}
if (-not (Test-Path -LiteralPath $csvOut)) {
    Write-Host "CSV not created: $csvOut" -ForegroundColor Red
    exit 2
}
Write-Host "CSV: $csvOut"

$pyPick = Join-Path $Root 'examples\miniqmt_research\daily_picks\picks_report.py'
$pickArgs = @($pyPick, $csvOut, $finalReport, '25')
$pickOut = @(& python @pickArgs 2>&1)
$exitPick = $LASTEXITCODE
$pickOut | ForEach-Object { Write-Host $_ }
if ($exitPick -ne 0) {
    Write-Host "picks_report.py failed ExitCode=$exitPick" -ForegroundColor Red
    exit 3
}

Copy-Item -LiteralPath $finalReport -Destination $latestPicks -Force

$sectorSum = Join-Path $Root 'examples\miniqmt_research\data\sector_run_auto_summary.txt'
$db = Join-Path $Root 'examples\miniqmt_research\data\miniqmt.sqlite'
$err = Join-Path $Root 'examples\miniqmt_research\data\sector_sync_full.err.log'
$append = @"

========================================================================
Pipeline outputs (UTF-8)
- sector stdout log: $log
- sector stderr log: $err
- SQLite: $db
- sector sync summary: $sectorSum
- daily_picks dir: $dailyDir
- dated screen CSV: $csvOut
- latest screen CSV: $latestCsv
- dated picks report: $finalReport
- latest picks report: $latestPicks
========================================================================
"@
Add-Content -LiteralPath $finalReport -Value $append -Encoding utf8

Write-Host ""
Write-Host "========== ALL DONE ==========" -ForegroundColor Green
Write-Host "Report: $finalReport"
Write-Host "Latest picks: $latestPicks"
Write-Host "Sector summary: $sectorSum"
Write-Host "CSV: $csvOut"
Write-Host "Latest CSV: $latestCsv"
