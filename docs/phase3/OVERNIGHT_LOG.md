# 밤새 Phase 3 기초 작업 보고서

**시작 시각**: 2026-05-20 23:00 KST
**종료 시각**: 2026-05-21 07:36 KST 경 (사용자 출근 시점)
**작업자**: Claude Opus 4.7 (자율 모드)
**스코프 격리**: 모든 결과물은 `c:\Users\user\projects\overnight_phase3\` 안에만. 기존 프로젝트(`도로교통법-한눈에/`, `도로교통법-한눈에-tutor/`, `판례조회-AI도구/`) 파일은 **읽기만** 함.

---

## 🎯 최종 요약 (아침에 봐야 할 핵심)

### ✅ 완료한 것
1. **6개 법령 메타데이터 조회** — 총 **435 버전** 확인
2. **본문/연혁 수집 최종 결과** (백그라운드 완료):
   | 법령 | 결과 | 비고 |
   |---|---|---|
   | 교특법 | ✅ 16/16 | 178KB |
   | 특가법 | ✅ 44/44 | 1.1MB |
   | 자동차관리법 | ✅ 145/145 | 15MB |
   | 여객운수사업법 | ✅ 102/102 | 7.8MB |
   | 화물운수사업법 | ⚠️ 52/74 (22건 실패) | 3.2MB — 일부 MST 조회 실패, 재시도 필요 |
   | 형사소송법 | ❌ 0건 | 메타에선 54건이었으나 본문 단계서 search_history 실패. 재실행 필요 |
3. **화이트리스트 초안** (`design/sources_config_draft.json`)
   - 특가법: 제5조의3·5조의11·5조의13 (뺑소니·위험운전·민식이법)
   - 형소법: 음주측정·체포·기소 관련 11개 조문
   - 자관법·운수사업법은 후보만 — 사용자 확정 필요
4. **viewer 다중 법령 UI 설계서** (`design/viewer_multi_law_ui.md`)
   - 드롭다운 통합 + 단일/3단 모드 자동 전환
   - lazy load + URL 호환성
   - Stage 3 세분화 (3-1~3-6)
5. **text_diff.json 의미 변경 필터 시제품** (`scripts/filter_meaningful_diffs.py`)
   - 12.7MB 입력 → **4,974건 의미 있는 변화** 추출 (신설삭제 794 + 의미변경 4,180)
   - 자구·띄어쓰기 변경 630건 + 미세 변경 166건 제외
   - 출력: `data/meaningful_diffs.json` (8MB)

### ⚠️ 발견한 함정 (의사 결정 필요)

#### 함정 1: 조문번호 시계열 의미 불일치 (가장 중요)
`text_diff.json`은 조문번호로 단순 매칭하지만 **조문번호의 의미가 시간에 따라 바뀜**:
- 예전 제50조 = "도로공사신고" / 현재 제50조 = 운전자 의무 (안전띠)
- 예전 제25조 = "긴급자동차" / 현재 제25조 = 교차로 통행방법
- 예전 제44조 = "운전자 준수사항" / 현재 제44조 = 음주운전 금지

**해결 방안 (Stage 7 구현 시)**:
- 각 조문에 "현행 의미 시작 시점" 메타데이터 추가 → 그 이후 변화만 학습 콘텐츠
- 또는: 조문 제목이 현행과 일치/유사한 변화만 학습용
- 별표 데이터(메인 viewer)에서 이미 처리 중인지 확인 권장

#### 함정 2: `find_recent_revision()` 버그 (Codex 발견, Phase 2 영향)
`build_tutor_content.py:257` — 시행일자 필터링 없이 첫 매칭 개정만 반환. `daily_2026-05-22.json`에 **2026-08-01 시행 예정 개정**이 카드에 섞임. **Stage 5 또는 Phase 2 마무리 시점에 같이 수정 권장**: `시행일자 <= 카드 날짜` 필터.

#### 함정 3: 교특법 판례 OPEN API 엔드포인트 (Stage 6 영향)
`판례조회-AI도구/update_cases.py:35`는 `target=decc` (행정심판재결례) 사용. 교특법·뺑소니·민식이법은 **형사 사건**이라 decc에 없음. **`target=prec` (법원판례)로 재시도 필요**. 시제품 실행 결과 4개 쿼리 모두 0건.
→ Stage 6 본 작업 시 `target=prec` + 사건명 검색 또는 도교법 사건과 함께 검색.

### 📊 자료 영향력 평가
- **즉시 활용 가능**: 6개 법령 본문 (수집 완료 후), 의미 변경 필터 결과 4,974건
- **Stage 5 작업 시 영향**: schedule.json 마이그레이션 위험 (Codex 함정 2 같이 처리)
- **Stage 6 재설계 필요**: 판례 추가 수집 패턴 (`target=prec` 전환)

### 🚫 자율 진행 안 한 것 (사용자 확인 후 결정)
- 기존 프로젝트 코드 수정 (build_tutor_content.py, viewer.html 등)
- git commit/push
- Phase 2 영역 (RPD 회복 후 사용자 검증 예약)
- schedule.json 마이그레이션 (Stage 5, 최대 위험)

---

## 산출물 위치 (절대경로)

```
c:\Users\user\projects\overnight_phase3\
├── OVERNIGHT_LOG.md                          ← 이 파일
├── data\
│   ├── _collection_summary.json               ← 6개 법령 수집 요약
│   ├── _collection_run.log                    ← 수집 실행 로그
│   ├── _extra_cases_summary.json              ← 판례 시제품 결과 (0건, 함정3 참조)
│   ├── _diff_samples.json                     ← 안전띠·우회전 등 샘플 변화
│   ├── meaningful_diffs.json                  ← 의미 변경 4,974건 (8MB)
│   ├── extra_cases_candidates.json            ← (현재 빈 배열)
│   ├── tlspc_history.json                     ← 교특법 16버전 본문
│   ├── tkga_history.json                      ← 특가법 44버전 본문
│   ├── car_mgmt_history.json                  ← 자관법 145버전 (진행 중)
│   ├── passenger_transport_history.json       ← (진행 중)
│   ├── cargo_transport_history.json           ← (대기)
│   └── crim_proc_history.json                 ← (대기)
├── design\
│   ├── sources_config_draft.json              ← 튜터 화이트리스트 초안
│   └── viewer_multi_law_ui.md                 ← viewer 다중 법령 설계서
└── scripts\
    ├── collect_new_laws.py                    ← 6개 법령 본문/연혁 수집
    ├── filter_meaningful_diffs.py             ← text_diff 의미 변경 필터
    └── collect_extra_cases.py                 ← 판례 추가 수집 시제품
```

---

## 다음 단계 추천 (사용자 결정용)

### 즉시
1. **백그라운드 수집 완료 확인** — `tail -10 data/_collection_run.log` 또는 `_collection_summary.json` 확인
2. **함정 3 검증** — `target=prec` 엔드포인트로 collect_extra_cases.py 재실행 검토
3. **화이트리스트 검토** — `design/sources_config_draft.json`의 자관법·운수사업법 조문 확정

### 단기 (Phase 2 완료 후)
4. **함정 2 수정** — `build_tutor_content.py:257` find_recent_revision 시행일자 필터 추가
5. **함정 1 해결책 적용** — text_diff 활용 시 조문번호 의미 시점 기준 추가

### Stage 진입 (Phase 3 본격)
6. Stage 1 — viewer 데이터 구조 리팩터링부터 시작 (가장 위험 낮음)

---

## 진행 상태

(작업 진행에 따라 업데이트됨 — 마지막 섹션 "최종 요약"이 아침에 봐야 할 핵심)

---

### [00:00 경] Codex 사전 설계 검증 (Phase 3 + 첫 스크립트)

**호출**: PowerShell Start-Job + codex.cmd exec --ignore-user-config --skip-git-repo-check --sandbox read-only
**상태**: ✅ 응답 받음 (cmd 출력 인코딩 깨짐 → 다음 호출부터 PYTHONIOENCODING 강제)

**Codex 지적 (해석)**:
1. ⚠️ **(스코프 밖) `build_tutor_content.py:257` `find_recent_revision()` 버그**
   - 시행일자 필터링 없이 첫 매칭 개정만 반환
   - `daily_2026-05-22.json`에 **2026-08-01 시행 예정 개정**이 카드에 섞임
   - 권장: `시행일자 <= 카드 날짜` 필터 추가
   - **내 자율 작업 범위 밖** — 아침에 사용자가 결정 (Phase 2 마무리 또는 Stage 5 손볼 때 같이)
2. ⚠️ Phase 3 푸시 단계 미상 — GitHub Actions·VAPID·Cloudflare Worker 영역은 8단계 플랜에 없음 (현재는 카드 생성·viewer 확장만)
3. ⚠️ 자동 생성 검증 체크리스트 권장 — daily 스키마, llm_status 비율, 주말 스킵 등 (이건 자율 작업 영역 아님, Phase 2/Stage 5 작업 시 적용)

**적용**:
- 격리 원칙 강화: 새 스크립트는 `overnight_phase3/data/`만 read/write
- find_recent_revision 버그는 별도 항목으로 사용자 보고
- hook 통과 → 코드 작성 진행

