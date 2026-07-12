# 로컬 자동 갱신 (무료 대안)
# =========================================================================
# 배경: 국가법령정보 API(www.law.go.kr)가 GitHub Actions(해외 IP)를 차단해
#       update.yml 자동 갱신이 2026-05 이후 매주 실패. 한국 IP인 이 PC에서
#       주기 실행해 데이터를 수집·빌드하고 GitHub에 push한다.
#       (Pages 배포는 push 시 자동 트리거)
#
# 작업 스케줄러 등록: scripts/register_local_update_task.ps1 참조
#   - 주 1회 + "놓친 작업은 가능한 한 빨리 실행" + "이미 실행 중이면 새 인스턴스 금지"
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

# 중복 실행 방지 (겹침 시 인덱스·JSON 동시수정 차단)
if (Test-Path $lock) {
    Log "이미 실행 중(lock 존재) — 이번 실행 스킵"
    exit 0
}
New-Item $lock -ItemType File -Force | Out-Null

try {
    Log "===== 로컬 자동 갱신 시작 ====="

    # 1) 최신 master 동기화 (로컬 설정파일 미커밋 변경이 있으면 ff-only가 막힐 수 있음 → 실패 시 중단)
    git checkout master 2>&1 | Out-File $log -Append -Encoding utf8
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

    # 3) 배포 산출물만 커밋 (로컬 설정파일 serve.py/.gitignore는 제외).
    #    multi-group이므로 viewer*.html(7개 그룹) 전부 포함.
    git add web_data/ alarm/data/ viewer*.html 2>&1 | Out-File $log -Append -Encoding utf8
    git add data/attached_tables.json 2>$null

    $changes = git status --porcelain web_data alarm/data viewer*.html data/attached_tables.json
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

    Log "===== 종료(성공) ====="
}
finally {
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
}
