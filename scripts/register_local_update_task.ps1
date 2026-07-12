# 로컬 자동 갱신 작업 스케줄러 등록 (1회 실행)
# =========================================================================
# 이 스크립트를 한 번 실행하면 Windows 작업 스케줄러에 주 1회 자동 갱신 작업이
# 등록된다. (관리자 권한 불필요 — 현재 사용자 작업으로 등록)
#
#   실행: PowerShell에서
#     powershell -ExecutionPolicy Bypass -File scripts\register_local_update_task.ps1
#
# 등록 옵션:
#   - 매주 월요일 09:00 실행
#   - 놓친 작업은 PC를 켠 뒤 가능한 한 빨리 실행 (StartWhenAvailable)
#   - 이미 실행 중이면 새 인스턴스 시작 안 함 (IgnoreNew)
#   - 네트워크 연결 시에만 실행
#   - 배터리 전원에서도 중단 안 함 (노트북 대응)
# =========================================================================

$proj   = "C:\Users\user\projects\도로교통법-한눈에"
$script = Join-Path $proj "scripts\local_auto_update.ps1"
$taskName = "도교법-로컬자동갱신"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 9:00AM

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -MultipleInstances IgnoreNew `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings `
    -Description "국가법령정보 API가 GitHub Actions 해외IP를 차단하는 문제의 무료 대안 — 한국 IP인 이 PC에서 주1회 법령데이터 수집·빌드·push (Pages 자동배포)" `
    -Force

Write-Output "✅ 작업 등록 완료: $taskName (매주 월 09:00, 놓친 작업 자동 실행)"
Write-Output "   최초 1회는 '작업 스케줄러'에서 수동 실행하여 push까지 정상 동작을 확인하세요."
Write-Output "   로그: $proj\local_update.log"
