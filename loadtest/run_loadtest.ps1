<#
.SYNOPSIS
    Запускает нагрузочный тест COHUB (Locust, 100 пользователей) и формирует HTML-отчёт.

.DESCRIPTION
    Headless-прогон Locust против работающего приложения. По умолчанию: 100
    пользователей, разгон 10/сек, длительность 2 минуты. Отчёт сохраняется в
    loadtest_report.html (+ CSV со статистикой).

    ВАЖНО: приложение должно быть уже запущено, например:
        cd cohub
        .\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000

.EXAMPLE
    .\loadtest\run_loadtest.ps1
    .\loadtest\run_loadtest.ps1 -Users 100 -RunTime 2m -TargetHost http://127.0.0.1:8000
#>
param(
    [int]$Users = 100,
    [int]$SpawnRate = 10,
    [string]$RunTime = "2m",
    # ВНИМАНИЕ: параметр НЕ называть $Host — это read-only автопеременная PowerShell,
    # биндинг такого параметра падает с VariableNotWritable ещё до запуска скрипта.
    [string]$TargetHost = "http://127.0.0.1:8000",
    [string]$Report = "loadtest_report.html"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

Write-Host "==> Locust: $Users пользователей, разгон $SpawnRate/с, время $RunTime, host $TargetHost" -ForegroundColor Cyan

& $python -m locust `
    -f (Join-Path $root "locust_loadtest.py") `
    --headless `
    --users $Users `
    --spawn-rate $SpawnRate `
    --run-time $RunTime `
    --host $TargetHost `
    --html (Join-Path $root $Report) `
    --csv (Join-Path $root "loadtest_stats")

Write-Host "==> Готово. HTML-отчёт: $Report" -ForegroundColor Green
