# 로컬 자동 갱신 (무료 대안)
# =========================================================================
# 배경: 국가법령정보 API(www.law.go.kr)가 GitHub Actions(해외 IP)를 차단해
#       update.yml 자동 갱신이 2026-05 이후 매주 실패. 한국 IP인 이 PC에서
#       주기 실행해 데이터를 수집·빌드하고 GitHub에 push한다.
#       (Pages 배포는 push 시 자동 트리거)
#
# 작업 스케줄러 등록: scripts/register_local_update_task.ps1 참조
#   - PC 로그온 시(+5분) + 매일 지정시각 (하루 1회 가드) + "이미 실행 중이면 새 인스턴스 금지"
#
# 로그: 프로젝트 루트 local_update.log  (10MB 초과 시 .old로 회전)
# =========================================================================

$proj = "C:\Users\user\projects\도로교통법-한눈에"
$log  = Join-Path $proj "local_update.log"
$lock = Join-Path $proj ".local_update.lock"
$env:PYTHONIOENCODING = "utf-8"
Set-Location $proj

function Log($msg) { "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg" | Out-File $log -Append -Encoding utf8 }

# 로그 회전 (10MB 초과 시)
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 10MB)) {
    Move-Item $log "$log.old" -Force
}

# 하루 1회 제한 (로그온마다 실행되므로 — 오늘 이미 성공했으면 스킵)
$lastFile = Join-Path $proj ".last_update_date"
$today = Get-Date -Format "yyyy-MM-dd"
if ((Test-Path $lastFile) -and ((Get-Content $lastFile -Raw).Trim() -eq $today)) {
    Log "오늘 이미 갱신 완료 — 스킵"
    exit 0
}

# 재시도 backoff (실패가 반복될 때 매 로그온 재실행 방지 — 마지막 시도 후 6시간 미만이면 스킵)
$attemptFile = Join-Path $proj ".last_attempt"
if (Test-Path $attemptFile) {
    try {
        $lastAttempt = [datetime]::ParseExact((Get-Content $attemptFile -Raw).Trim(), "yyyy-MM-dd HH:mm:ss", $null)
        if (((Get-Date) - $lastAttempt).TotalHours -lt 6) {
            Log "마지막 시도 후 6시간 미만 — 스킵(backoff)"
            exit 0
        }
    } catch { }  # 파싱 실패 시 그냥 진행
}
# 이번 시도 시각 기록 (성공·실패 무관 — backoff 기준)
(Get-Date -Format "yyyy-MM-dd HH:mm:ss") | Out-File $attemptFile -Encoding utf8 -NoNewline

# 중복 실행 방지 (겹침 시 인덱스·JSON 동시수정 차단)
# 단, 3시간 넘은 lock은 비정상 종료로 남은 stale lock으로 보고 무시한다.
if (Test-Path $lock) {
    $lockAge = (Get-Date) - (Get-Item $lock).LastWriteTime
    if ($lockAge.TotalHours -lt 3) {
        Log "이미 실행 중(lock 존재, $([int]$lockAge.TotalMinutes)분 경과) — 이번 실행 스킵"
        exit 0
    }
    Log "stale lock 발견(3시간 경과) — 제거 후 진행"
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
}
New-Item $lock -ItemType File -Force | Out-Null

try {
    Log "===== 로컬 자동 갱신 시작 ====="

    # 1) 최신 master 동기화
    #    이전 실행이 남긴 산출물(추적 파일)이 있으면 ff-only가 막히므로, pull 전에
    #    산출물을 HEAD로 원복한다(어차피 아래 update_all.py가 다시 생성).
    #    serve.py/.gitignore 등 로컬 개발 설정은 건드리지 않는다.
    git checkout master 2>&1 | Out-File $log -Append -Encoding utf8
    git checkout -- data/ docs/ web_data/ alarm/data/ viewer*.html 2>$null
    git pull --ff-only origin master 2>&1 | Out-File $log -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        Log "!! git pull --ff-only 실패(로컬 미커밋 변경·충돌 가능) — 중단. 수동 확인 요망"
        exit 1
    }

    # 2) 전체 갱신 (별표 PDF 다운로드는 오래 걸려 제외)
    Log "update_all.py --no-pdfs 실행 (30분~1시간 소요)"
    py update_all.py --no-pdfs 2>&1 | Out-File $log -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        Log "!! update_all.py 실패 — push 생략(다음 실행에서 재시도). log 확인 요망"
        exit 1
    }

    # 2-1) 산출물 최소 검증 (exit 0이어도 내용이 깨질 수 있으므로 — 깨진 빌드 push 방지)
    $bad = @()
    if (-not (Test-Path "viewer.html")) { $bad += "viewer.html 없음" }
    elseif ((Get-Item "viewer.html").Length -lt 50KB) { $bad += "viewer.html 비정상($((Get-Item 'viewer.html').Length) bytes < 50KB)" }
    if (-not (Test-Path "web_data/data_core.js")) { $bad += "web_data/data_core.js 없음" }
    if (-not (Test-Path "data/attached_tables.json")) { $bad += "data/attached_tables.json 없음" }
    elseif ((Get-Item "data/attached_tables.json").Length -lt 5MB) { $bad += "attached_tables.json 비정상(<5MB)" }
    if ($bad.Count -gt 0) {
        Log "!! 산출물 검증 실패 — push 생략: $($bad -join ', ')"
        exit 1
    }
    Log "산출물 검증 통과"

    # 3) 산출물 커밋 (로컬 설정파일 serve.py/.gitignore는 제외).
    #    data/·docs/까지 포함해 커밋해야 다음 실행의 pull이 막히지 않는다.
    #    (data/ 대용량 원본은 .gitignore로 자동 제외됨)
    git add data/ docs/ web_data/ alarm/data/ viewer*.html 2>&1 | Out-File $log -Append -Encoding utf8

    $changes = git status --porcelain data docs web_data alarm/data viewer*.html
    if ($changes) {
        $today = Get-Date -Format "yyyy-MM-dd"
        git commit -m "chore: 로컬 자동 갱신 $today" 2>&1 | Out-File $log -Append -Encoding utf8
        git push origin master 2>&1 | Out-File $log -Append -Encoding utf8
        if ($LASTEXITCODE -ne 0) {
            Log "!! git push 실패(원격 앞섬·인증만료 등) — 커밋은 로컬에 남음. 수동 push 요망"
            exit 1
        }
        Log "변경 push 완료 → GitHub Pages 자동 배포"
    } else {
        Log "변경 없음 (갱신 사항 없음)"
    }

    # 오늘 성공 기록 (하루 1회 가드용 — 변경 유무와 무관하게 '오늘 확인함'을 기록)
    $today | Out-File $lastFile -Encoding utf8 -NoNewline
    Log "===== 종료(성공) ====="
}
finally {
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
}
