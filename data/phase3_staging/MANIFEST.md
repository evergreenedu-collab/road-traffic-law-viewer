# Phase 3 Staging — 신규 법령 자료

**생성일**: 2026-05-21 (S2-A)
**원본**: `c:\Users\user\projects\overnight_phase3\data\` (격리 작업 산출물)
**상태**: 보관만. 메인 viewer·튜터 빌드 파이프라인은 아직 미연결.

---

## 자료 목록 (6법령, OPEN API 수집)

| 파일 | 법령 | 버전 수 | 크기 | 비고 |
|---|---|---:|---:|---|
| `tlspc_history.json` | 교통사고처리 특례법 | 16 | 178KB | 시행령·시행규칙 없음 |
| `tkga_history.json` | 특정범죄 가중처벌 등에 관한 법률 | 44 | 1.1MB | 교통 관련 5조의3·5조의11·5조의13만 학습 대상 |
| `car_mgmt_history.json` | 자동차관리법 | 145 | 15MB | 시행령·시행규칙 별도 수집 필요 |
| `passenger_transport_history.json` | 여객자동차 운수사업법 | 102 | 7.8MB | 시행령·시행규칙 별도 수집 필요 |
| `cargo_transport_history.json` | 화물자동차 운수사업법 | 52 | 5.2MB | 22건 MST 본문 실패, 재시도 필요 |
| `crim_proc_history.json` | 형사소송법 | 54 | 13MB | 시행령·시행규칙 없음. 일부 조문만 학습 대상 |
| `_collection_summary.json` | 수집 요약 | - | - | 법령별 성공/실패 카운트 |

**자료 포맷**: OPEN API `lawService.do?target=law&MST=...` 응답을 가공한 JSON.
- `기본정보`: 법령ID·공포일자·시행일자·제개정구분·소관부처
- `조문`: 조문번호·조문가지번호·조문제목·조문시행일자·조문제개정유형·조문내용
- `부칙`: 부칙공포일자·부칙공포번호·부칙내용
- `제개정이유`: 텍스트
- `_검색메타`: 수집 시 메타 정보

기존 `data/article_history.json` 포맷과 **다릅니다**. 통합 시 변환기 필요.

---

## ⚠️ 메인 파이프라인 미연결

다음 파이프라인 미동작 (코드 변경 안 됨):
- `build_3tier_map.py:299` 이후 로직이 `시행령`·`시행규칙` 키 전제 → 단일 법률 분기 필요
- `LAWS = LAW_GROUPS["road"]` 고정 → 실행 대상 변경 불가
- 출력 경로 road 전용 (`three_tier_map.json`, `article_history.json` 등)
- `viewer.html:676-681`이 `data_core.js` 등 6개 파일 고정 로드

## 통합 작업 순서 (향후 S3와 묶음)

1. **수집기 멀티 그룹 지원** — `collect_full_history.py`·`collect_article_history.py`가 `LAW_GROUPS["tlspc"]` 등을 받아 실행. `phase3_staging/` 자료는 재수집 회피용 캐시로 활용 가능
2. **build_3tier_map 단일 법률 분기** — `has_subordinate=false`이면 시행령·시행규칙 컬럼 없이 처리
3. **output 파일 그룹 접두사** — `three_tier_map_tlspc.json` 등
4. **viewer.html 다중 법령 UI** (S3 본 작업) — 드롭다운 + 단일/3단 모드 자동 전환
5. **튜터 study_whitelist.json 활용** — `도로교통법-한눈에-tutor/tutor/data/study_whitelist.json`의 화이트리스트 27개 조문만 학습

---

## 사용자 결정 사항 (반영됨)
- A. viewer UI = 드롭다운 통합 (`design/viewer_multi_law_ui.md` 설계서)
- B. 튜터 운영 = B3 고정 슬롯 3:1:1
- C. 수집 범위 = 전체 수집 + 튜터 화이트리스트 (study_whitelist.json)
- D. 조문 연혁 = `history_evolution` 필드 ✅ S7 통합 완료
- F3. 어린이 보호구역 = commentary 카드 대체 (코드 자동 분기)
- F5. 자관법·운수사업법 화이트리스트 = 확정 (study_whitelist.json)

## 관련 산출물 (이미 통합 완료)
- `도로교통법-한눈에-tutor/tutor/data/meaningful_diffs.json` — S7 필드용 의미 변화 자료
- `도로교통법-한눈에-tutor/tutor/data/court_cases_data.json` — 758 + 218 = 976건 (S6)
- `도로교통법-한눈에-tutor/tutor/data/study_whitelist.json` — 7법령 화이트리스트
- `판례조회-AI도구/판례_통합_phase3.txt` — 신규 형사 판례 218건
