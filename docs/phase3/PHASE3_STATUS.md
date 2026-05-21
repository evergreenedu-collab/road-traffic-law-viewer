# Phase 3 진행 상황 + 향후 To-Do

**기준 시각**: 2026-05-21 오전
**플랜 원본**: `C:\Users\user\.claude\plans\3-synthetic-lagoon.md` (8 Stage)
**격리 산출물**: `c:\Users\user\projects\overnight_phase3\`

---

## 1. 원래 8 Stage 진행 상태

| Stage | 내용 | 위험 | 상태 | 비고 |
|---|---|---|---|---|
| **S1** | viewer 데이터 구조 리팩터링 (LAWS dict-of-dict) | 中 | ✅ **2026-05-21 완료 (S1-A만)** | S1-A: 3파일에 `LAW_GROUPS={"road":...}` wrapper + alias. 회귀 0. Codex 사전·사후 거침. **S1-B/C 스킵 결정**: 출력 파일명 변경은 viewer.html과 묶여 있어 S3에서 한 번에 처리하기로. S1-A만으로 multi-law 진입(S2/S4) 충분. **multi-law 진입 시 정리 사항**: SELF_LAWS(build_3tier_map:513) · type_to_name(build_cascade_events:265) · LAW_GROUPS 3파일 중복 · 출력 경로 road 하드코딩 |
| **S2** | 교특법 데이터 수집 추가 | 低 | 🟡 **S2-A 완료 (staging 보관)** | `도로교통법-한눈에/data/phase3_staging/`에 6법령 본문 + MANIFEST 보관. Codex 발견: build_3tier_map:299 이후 로직이 시행령·시행규칙 전제라 단일 법률 분기 추가가 S3와 묶임. 자료는 준비 완료. S2-B(나머지 5법령 추가 검토)는 같은 staging에 이미 포함 |
| **S3** | viewer.html 다중 법령 UI | 高 | 🟡 **S3-1-a/b 완료, S3-1-b-4 미진행** | S3-1-a(드롭다운 UI)·S3-1-b-1(EMPTY_LAW 단일 법률 분기)·S3-1-b-2(build_3tier_map --group)·S3-1-b-3(generate_viewer --group + viewer 별도 페이지) 완료. tlspc 시범 빌드 결과 viewer JS 4가지 깨짐(F8) 발견 → 일시 롤백 (드롭다운 tlspc 다시 disabled). S3-1-b-4(viewer JS multi-law 분기 보강)가 남은 본 작업 |
| **S4** | 특가법·형소법·자관법·운수사업법 수집 | 低 | 🟡 **staging 보관 완료** | S2-A와 같이 5법령 본문 모두 staging에 보관. 통합은 S3와 묶음 (build_3tier_map 단일 법률 분기 + viewer UI). 화물 22건 실패 재시도는 사용자 결정 |
| **S5** | 튜터 schedule 마이그레이션 | 中 | ⏳ 미착수 | **최대 위험** — Phase 2 안정화 후 진행 권장 |
| **S6** | 교특법 판례 추가 수집 | 低 | ✅ **2026-05-21 통합 완료** | 218건 → `판례_통합_phase3.txt`로 변환 + `build_indexes.py:674-720` 누적 처리 수정. **누적 976건 (758+218, 충돌 0)**. 조문 매핑 증가: 제44조 127→166, 제54조 15→40, 제43조 75→118, 제148의2조 18→31. Codex 사전·사후 검증 거침 |
| **S7** | meaningful_diffs + history_evolution 필드 | 中 | ✅ **2026-05-21 통합 완료** | meaningful_diffs.json 메인 이동 + build_tutor_content.py 전반 수정: load_indexes·find_resources·_build_context·프롬프트·verify_content·card 저장. 카드 version 5→6. Codex 사전·사후 검증 거침. 권장 보강 3가지(날짜 정규식 견고성·날짜 인용 필수·빈 키워드 후순위) 적용 |
| **S8** | 튜터 B3 슬롯 로직 (3:1:1) | 中 | ⏳ 미착수 | S5 완료 후 |

---

## 2. 새로 발견한 함정·추가 작업

| ID | 내용 | 영향 | 우선순위 |
|---|---|---|---|
| **F1** | ✅ **2026-05-21 수정 완료** — `find_recent_revision()` target_date 인자 + 시행일자 필터 + 후보 정렬 + 날짜 정규화(YYYYMMDD). 카드 `recent_revision.시행일자`도 조문시행일자 우선. 19건 미래 시행 개정이 더 이상 안 섞임. **단 daily_2026-05-22.json 등 기존 카드는 재생성 전까지 옛 값 유지.** **F1-α 잔여 권장**: `_normalize_date`가 'YYYY.M.DD' 단자리 형식은 None 반환 (recent_revisions.json엔 없으나 견고성 보강 여지). | Phase 2 카드 정확도 | ✅ 완료 |
| **F2** | ✅ **2026-05-21 해결** — `filter_meaningful_diffs.py` 보강: 현행 조문 제목(`index_law_articles`) 인덱스 + 변화 제목 정규화 비교(괄호 제거·한자→한글·공백 정리) + 신설·본조신설도 적용. 법률 1,209건 옛 의미 제외(법률만, 시행령·규칙은 별도 인덱스 필요). 제50·25·12·44조 채택 결과가 현행 의미만으로 깨끗. Codex 사전·사후 검증 거침. 출력: `data/meaningful_diffs.json` + `_diff_excluded_old_meaning.json` | Stage 7 정밀화 | ✅ 완료 (법률) |
| **F3** | ✅ **2026-05-21 결정** — commentary 카드 대체 (조문 + 해설집 + 수사실무 자료로 학습). 코드는 이미 `analysis_type='commentary'` 자동 전환 구현돼 있음. 별도 작업 불필요. 향후 어린이 보호구역 판례 자료가 확보되면 그때 보강 | 어린이 보호구역 학습 카드 | ✅ 완료 (commentary 모드) |
| **F4** | ✅ **2026-05-21 해결** — `generate_viewer.py` main()에 `build_ts = time.strftime("%Y%m%d%H%M%S")` + `re.sub`로 6개 script src에 `?v=빌드시각` 자동 주입. 시크릿 창 없이도 새 데이터 인식. 매주 월 자동 갱신 시 작동 | UX | ✅ 완료 |
| **F8** | viewer.html JavaScript가 도교법 3단 구조 가정 — 단일/2단 법령(tlspc) 모드에서 4가지 깨짐 발견 (외부 링크 '도로교통법' 하드코딩 · 시행령 카드 미렌더링 · 연혁 패널 비어 있음 · 조문 클릭 무반응). S3-1-b-3 시범 후 일시 롤백. **S3-1-b-4가 본격 보강 단계** (1-2시간 추정) | viewer multi-law 활성화 | 🔴 높음 (S3 진행 전 필수) |
| **F5** | ✅ **2026-05-21 확정** — `tutor/data/study_whitelist.json` 신규. 7개 법령 / 화이트리스트 27개 조문(자관법 6·여객 4·화물 3·특가법 3·형소법 11) + all 모드 2개(도교법·교특법). Stage 1·4·8 작업 시 build_tutor_content가 활용 | 튜터 학습 콘텐츠 품질 | ✅ 완료 |
| **F6** | ✅ **2026-05-21 해결** — `build_indexes.py:721-732` `_court_date_key` 헬퍼 + `sorted(sorted(set(cids)), key=_court_date_key, reverse=True)`. date desc + cid asc(결정성). 6가지 날짜 형식 정규식 보강(`YYYY.MM.DD`·`YYYY.M.DD`·`YYYY-MM-DDTHH:MM:SS`·`YYYY년 M월 D일`·`YYYYMMDD`·빈 값). 제44·54·43·148의2 조문 앞 6건이 모두 최신(2026·2025년) 사건으로 확인. Codex 사전·사후 검증 거침 | S6 효과 발휘 | ✅ 완료 |
| **F7** | `case_no#num` 패턴(같은 사건번호 다중 cid)이 `build_tutor_content.py:208`에서 case_no로 다시 합쳐짐. 현재 충돌 0이라 무해. 미래 판례 자료 추가 시 주의 | 미래 위험 | 🟢 낮음 |

---

## 3. 격리 → 본 프로젝트 통합 작업

밤새 작업이 모두 `overnight_phase3/` 격리 디렉토리에 있음. 본 프로젝트로 옮기는 단계가 필요.

| ID | 격리 산출물 | 통합 대상 | 비고 |
|---|---|---|---|
| **I1** | `data/tlspc_history.json` 외 5개 법령 본문 | `도로교통법-한눈에/data/` 또는 별도 `multi_law/` 폴더 | S1·S2·S4 시작 시 |
| **I2** | `data/extra_court_cases_data.json` (수집 중) | `도로교통법-한눈에-tutor/tutor/data/court_cases_data.json`에 병합 또는 별도 파일로 | 사건번호 dedup은 이미 됨 |
| **I3** | `data/meaningful_diffs.json` (8MB) | 메인 viewer 프로젝트 data/ | S7 시작 시. F2 해결 후 정밀 재추출 권장 |
| **I4** | `design/sources_config_draft.json` | `도로교통법-한눈에-tutor/tutor/data/sources_config.json` | F5 검토 후 통합 |
| **I5** | `design/viewer_multi_law_ui.md` | 참조용 (코드 변경은 S3에서) | 변경 가이드 |

---

## 4. 우선순위별 다음 단계 (2026-05-21 저녁 갱신)

### ✅ 오늘 완료한 것 (master 푸시됨)
- **F1**·**F2**·**F3**·**F5**·**F6** — 함정 5개
- **S1-A**·**S2-A**·**S4**(staging)·**S6**·**S7** — Stage 5개
- **F4** + **S3-1-a** + **S3-1-b** (1·2·3 모두 코드 완료, tlspc 시범 후 롤백)

### 🥇 다음 세션 진입점
- **S3-1-b-4** (1-2시간) — **viewer.html JavaScript multi-law 분기 보강**
  - F8 4가지 깨짐 해결: 외부 링크 동적 / 시행령 카드 렌더 / 조문 클릭 / 연혁 안내
  - 완료 시: `GROUP_ENABLED = {"road", "tlspc"}` 활성화 + `py build_3tier_map.py --group tlspc` + `py generate_viewer.py --group tlspc` 재실행 → viewer_tlspc.html 정상 동작

### 🥈 그 다음 (Phase 3 마무리)
- **S5 + S8** (튜터 multi-law, 3-4시간) — schedule 마이그레이션 + B3 슬롯
- **다른 5법령 LAW_GROUPS 추가** — 특가법·자관법·여객·화물·형소법 MST 등록
- **timeline·cascade·diff 파이프라인 multi-law** — article_history·text_diff 등도 group별

### 🔄 보류
- F7 (case_no#num 미래 위험, 현재 무해)
- 어린이 보호구역 판례 외부 자료 (F3는 commentary 대체로 결정 완료)

---

## 5. 현재 보유 자료 요약 (모두 master에 통합됨)

```
도로교통법-한눈에/ (master 정본)
├── viewer.html · web_data/data_*.js              ← 도교법 viewer (F4 캐시버스팅 적용)
├── data/phase3_staging/                          ← S2-A: 6법령 본문/연혁 (42MB)
├── docs/phase3/                                  ← 통합 작업 아카이브
│   ├── README · PHASE3_STATUS · OVERNIGHT_LOG
│   ├── scripts/ (8개)
│   └── design/ (2개)
├── build_3tier_map.py                            ← LAW_GROUPS {road, tlspc} + --group
├── generate_viewer.py                            ← --group + suffix + lazy graceful
└── tutor/data/
    ├── meaningful_diffs.json                     ← S7 의미 변화 (8MB, 법률 3,439건)
    ├── study_whitelist.json                      ← F5 화이트리스트 (7법령 27조문)
    ├── court_cases_data.json                     ← S6 통합 976건
    └── daily_2026-06-01·02·03.json               ← Phase 2 시범 카드
```

---

## 6. 핵심 결정 사항 (모두 결정 완료)

1. ~~F1 수정 시점~~ → ✅ Phase 2 보강과 같이
2. ~~F5 화이트리스트~~ → ✅ 확정 (`study_whitelist.json`)
3. ~~F3 어린이 보호구역~~ → ✅ commentary 대체
4. ~~격리 산출물 통합~~ → ✅ `docs/phase3/` + tutor·viewer 자료 모두 master

### 새 결정 대기 (다음 세션)
- **S3-1-b-4 진입 시점** — viewer JS 보강. Phase 3 viewer 활성화 전 필수
- **다른 5법령 LAW_GROUPS** — S3-1-b-4 끝나면 멀티 viewer 의미 있음
