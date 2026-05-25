# Phase 3 진행 상황 + 향후 To-Do

**기준 시각**: 2026-05-26 (build_cascade_events 일반화 + Phase 2 빈필드폴백 머지 — PR #21·#22)
**플랜 원본**: `C:\Users\user\.claude\plans\3-synthetic-lagoon.md` (8 Stage)
**격리 산출물**: `c:\Users\user\projects\overnight_phase3\` (모든 산출물 master 통합 완료, 격리 dir은 휴지통)

---

## 1. 원래 8 Stage 진행 상태

| Stage | 내용 | 위험 | 상태 | 비고 |
|---|---|---|---|---|
| **S1** | viewer 데이터 구조 리팩터링 (LAWS dict-of-dict) | 中 | ✅ **2026-05-21 완료 (S1-A만)** | S1-A: 3파일에 `LAW_GROUPS={"road":...}` wrapper + alias. 회귀 0. Codex 사전·사후 거침. **S1-B/C 스킵 결정**: 출력 파일명 변경은 viewer.html과 묶여 있어 S3에서 한 번에 처리하기로. S1-A만으로 multi-law 진입(S2/S4) 충분. **multi-law 진입 시 정리 사항**: SELF_LAWS(build_3tier_map:513) · type_to_name(build_cascade_events:265) · LAW_GROUPS 3파일 중복 · 출력 경로 road 하드코딩 |
| **S2** | 교특법 데이터 수집 추가 | 低 | 🟡 **S2-A 완료 (staging 보관)** | `도로교통법-한눈에/data/phase3_staging/`에 6법령 본문 + MANIFEST 보관. Codex 발견: build_3tier_map:299 이후 로직이 시행령·시행규칙 전제라 단일 법률 분기 추가가 S3와 묶임. 자료는 준비 완료. S2-B(나머지 5법령 추가 검토)는 같은 staging에 이미 포함 |
| **S3** | viewer.html 다중 법령 UI | 高 | ✅ **2026-05-22 7개 그룹 전체 활성화 완료** | road/tlspc/tkga/crim_proc/car_mgmt/passenger_transport/cargo_transport — 각 viewer_*.html + web_data/data_*_*.js 별도 생성. 법령유형 토글, 시행령 직접 진입, 위임 chip, 부칙 섹션, non-road 친절 안내(법령정보센터 링크), 자기참조 popupArticle(lawType), 알람 road 전용 분기 등 모두 동작. F11/F12 폴리시 완료 |
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
| **F8** | 🟢 **S3-1-b-4-a + b 완료, c 일부 잔여** — 도교법 3단 가정 4가지 깨짐 중 #1·#2·#3·#4 진행: ✅ #1 외부 링크 동적 + #2 시행령·시행규칙 조문 자체 진입(법령유형 토글 + renderSubLawArticle) + #3 시행령·시행규칙 모드 연혁 안내 박스 + #4 데이터 한계는 안내로 보완. 끝나면 GROUP_ENABLED tlspc 재활성화 가능 (자료 자체 검증은 별도) | viewer multi-law 활성화 | 🟢 거의 완료 |
| **F9** | ✅ **2026-05-21 밤 해결** (Codex 사후검증 발견) — 알람 iframe 메시지 핸들러가 URL의 `law=enf/enr`를 삭제하지 않아 시행령 모드에서 알람의 "연혁 보기" 클릭 시 시행령 모드 잔존으로 오해석. `window.addEventListener('message')` 안에 `url.searchParams.delete('law')` 추가 | 알람 → 연혁 흐름 | ✅ 완료 |
| **F10** | ✅ **2026-05-21 밤 해결** (Codex 사후검증 발견) — popupArticle 모달의 "이 조문 화면으로 이동" 버튼이 `goArticle(joKey)`만 호출 → 시행령/시행규칙 모드에서 누르면 시행령 조문으로 이동하거나 alert. 버튼 onclick에 `switchLawType('법률')` 선행 추가 | 시행령 본문 안 "법 제X조" 팝업 흐름 | ✅ 완료 |
| **F11** | ✅ **2026-05-22 해결** — popupArticle(joKey, lawType) 확장. esc()의 prefix-less "제X조"는 currentLawType 기준 자기법 모달. _escLawType은 별표 전용으로 분리. TDZ 회피용 선언 위치 상단 이동. | 시행령 본문 내부 링크 정확도 | ✅ 완료 |
| **F12** | ✅ **2026-05-22 해결** — 별표 모달 PDF 파일명·타법개정 안내 문구 도교법 하드코딩 제거. mapData.기준법령.법률.법령명 동적 사용 + 파일명 sanitize. esc 대신 escHtmlSimple로 _escLawType 상태 누수 회피. | 다중 법령 정합성 | ✅ 완료 |
| **F13** | 본문 호·목내용에 빈 줄 다수 — 도교법 제2조 등에서 표시 깨짐. _normalizeBlankLines로 \n\s*\n+ → \n 압축. hoListHtml·renderArticleBody에 적용. 2026-05-22 해결 | 본문 가독성 | ✅ 완료 |
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

## 4. 우선순위별 다음 단계 (2026-05-26 갱신)

### ✅ 누적 완료 (master)
- **함정 13개 해소**: F1·F2·F3·F4·F5·F6·F8·F9·F10·F11·F12·F13 (F7만 미래 위험으로 잔존)
- **Stage 완료**: S1-A·S2-A·S3(전체 7그룹)·S4(staging)·S6·S7
- **Phase 3 인프라 multi-group 완성**:
  - collect 스크립트 (004c9ea) — collect_full_history·collect_article_history·collect_attached_tables_history 모두 --group 지원
  - 빌드 파이프라인 (cc21e92) — build_text_diff·build_3tier_map·build_attached_tables·build_attached_tables_diff·download_table_pdfs 모두 --group 지원
  - update_all.py (4c35c41) — multi-group 자동 갱신 워크플로
  - LAW_GROUPS 7그룹 등록 — road·tlspc·tkga·crim_proc·car_mgmt·passenger_transport·cargo_transport
  - **build_cascade_events 매칭 로직 일반화 (PR #22, bb07ed3)** — LAWNAME_PAT 동적 컴파일 + 법령명 공백 유연 매칭 + type_to_name 그룹별 dict (2026-05-26)
- **Phase 2 보강**: case 카드 빈 필드 폴백 처리 (PR #21, 017342e) — 재페어링 1회 + article 폴백 + schedule 갱신 (2026-05-26)
- **Stage 미진행**: S5·S8 (튜터 multi-law — 최대 위험)

### 🥇 다음 세션 진입점 (2026-05-26 갱신)
- **S5 + S8** (튜터 multi-law, 3-4시간, 최대 위험) — schedule.json을 도교법 3 + 교특법 1 + 회전 1 구조로 마이그레이션 + B3 슬롯 로직
- **LAW_REF_IN_TABLE 일반화** (build_cascade_events:53, Codex PR #22 사후검증 권장) — 별표 본문 법률 인용 패턴이 여전히 `(?:도로교통)?법\s*제` 식으로 road 중심. 다른 그룹 별표에서 `자동차관리법 제X조` 같은 인용 못 잡음. 짧은 작업 (1시간)
- **Phase 2 카드 재생성** — 화·목 case 카드 자동 생성 시 폴백 동작 실 운영 모니터링

### 🔄 보류
- F7 (case_no#num 미래 위험, 현재 무해)
- 어린이 보호구역 판례 외부 자료 (F3는 commentary 대체로 결정 완료)

## ⚠️ 작업 시 함정 (2026-05-26 경험)

**메모리 노트만 보고 작업 시작하지 말 것.** 메모리 노트가 한참 오래되어 이미 master에
머지된 작업을 "미완성"으로 가리키는 경우가 빈번. 헛수고 방지:
1. 세션 시작 시 `git log --oneline -30` 으로 master 실제 상태 먼저 확인
2. 메모리 노트 vs 코드 어긋나면 **코드를 정본**으로
3. `feature/daily-tutor-push` 같은 옛 분기 브랜치만 보지 말고 master HEAD 기준
4. 메인 워크트리(`도로교통법-한눈에/`)는 master 정본, tutor 워크트리(`도로교통법-한눈에-tutor/`)는 feature 브랜치 — 두 워크트리가 다른 브랜치라는 점 잊지 말 것

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
- ~~GROUP_ENABLED에 tlspc 추가 시범 빌드~~ → ✅ 완료 (af91878)
- ~~다른 5법령 LAW_GROUPS 등록~~ → ✅ 완료 (7그룹 모두 등록·활성화: ed6fe2d·9a62178·8d36b8d)
- **S5 + S8** (튜터 multi-law) — schedule 마이그레이션 + B3 슬롯. Phase 2 빈필드폴백 머지(PR #21)로 Phase 2 안정화 완료 — 이제 S5 진입 가능
