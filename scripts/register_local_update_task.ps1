# 로컬 자동 갱신 작업 스케줄러 등록 (1회 실행)
# =========================================================================
# 이 스크립트를 한 번 실행하면 Windows 작업 스케줄러에 자동 갱신 작업이
# 등록된다. (관리자 권한 불필요 — 현재 사용자 작업으로 등록)
#
#   실행: PowerShell에서
#     powershell -ExecutionPolicy Bypass -File scripts\register_local_update_task.ps1
#
# 등록 옵션:
#   - PC를 켤 때(로그온)마다 실행 + 5분 지연(부팅 직후 네트워크 안정 대기)
#     → PC를 자주 안 켜는 환경 대응. 하루 1회 제한은 local_auto_update.ps1의
#       .last_update_date 가드가 담당(로그온 여러 번 해도 하루 1회만 실제 갱신).
#   - 이미 실행 중이면 새 인스턴스 시작 안 함 (IgnoreNew)
#   - 네트워크 연결 시에만 실행
#   - 배터리 전원에서도 중단 안 함 (노트북 대응)
# =========================================================================

$proj   = "C:\Users\user\projects\도로교통법-한눈에"
$script = Join-Path $proj "scripts\local_auto_update.ps1"
$taskName = "도교법-로컬자동갱신"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""

# 트리거 2개 병행 — 하루 1회 제한은 local_auto_update.ps1의 .last_update_date 가드가 담당:
#   (1) 로그온 시 +5분  → PC를 껐다 켜는 환경에서 켤 때마다 잡음
#   (2) 매일 10:00      → 계속 켜두고 절전만 하는 환경에서 잡음(로그온 트리거는 절전 복귀를 못 잡음)
$tLogon = New-ScheduledTaskTrigger -AtLogOn
$tLogon.Delay = "PT5M"
$tDaily = New-ScheduledTaskTrigger -Daily -At 10:00AM
$trigger = @($tLogon, $tDaily)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -MultipleInstances IgnoreNew `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3)

try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings `
        -Description "law.go.kr(국가법령정보 API)이 GitHub Actions 대역을 차단하는 문제의 무료 대안 — 이 PC에서 로그온 시+매일 법령데이터 수집·빌드·push (Pages 자동배포)" `
        -Force -ErrorAction Stop | Out-Null
} catch {
    Write-Output "❌ 작업 등록 실패: $_"
    exit 1
}

Write-Output "✅ 작업 등록 완료: $taskName (PC 로그온 시 +5분 / 매일 10:00, 하루 1회)"
Write-Output "   하루 1회 제한은 local_auto_update.ps1의 .last_update_date 가드가 담당합니다."
Write-Output "   로그: $proj\local_update.log"
