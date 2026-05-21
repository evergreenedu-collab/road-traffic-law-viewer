# Phase 3 작업 아카이브 (2026-05-21 통합)

원래 `c:\Users\user\projects\overnight_phase3\` 격리 디렉토리에서 진행된 Phase 3 준비 작업의 산출물·스크립트·보고서를 메인 리포로 통합한 것.

## 구성

```
docs/phase3/
├── README.md                       ← 이 파일
├── PHASE3_STATUS.md                ← Phase 3 진행 상태 + 함정·결정사항
├── OVERNIGHT_LOG.md                ← 밤새 작업 로그
├── scripts/                        ← 격리 작업 시 쓴 Python 스크립트 (8개)
│   ├── collect_new_laws.py         ← 6법령 본문/연혁 OPEN API 수집
│   ├── filter_meaningful_diffs.py  ← text_diff → meaningful_diffs (F2 적용)
│   ├── convert_to_text_format.py   ← JSON 판례 → 판례_통합 텍스트 형식
│   ├── merge_court_cases.py        ← (deprecated) JSON 직접 병합 시도
│   ├── collect_extra_cases.py      ← 교특법 등 신규 판례 수집 (target=prec)
│   ├── fetch_prec_details.py       ← 판례 본문 수집 (lawService.do?target=prec)
│   ├── prototype_history_evolution.py ← S7 시제품
│   └── test_card_s7.py             ← S7 효과 카드 1장 강제 생성
└── design/                         ← 설계서·초안 (2개)
    ├── viewer_multi_law_ui.md      ← Stage 3 viewer.html 다중 법령 UI 설계서
    └── sources_config_draft.json   ← (deprecated) study_whitelist.json으로 통합됨
```

## 향후 활용 시 주의

스크립트들은 격리 dir(`overnight_phase3/data/`) 기준 절대경로를 가정합니다.
메인 리포에서 재실행하려면 각 스크립트 상단의 경로 상수를 수정해야 합니다.

예 (`collect_new_laws.py`):
```python
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
assert ROOT_DIR.name == "overnight_phase3"   # ← 이 assert는 수정 또는 제거
DATA_DIR = ROOT_DIR / "data"                 # ← 메인 리포 경로로 변경
```

## 통합된 산출물 (이미 메인 리포에 있음)

이 아카이브에 안 들어 있고 이미 메인 코드/자료에 통합된 것:
- `tutor/data/meaningful_diffs.json` — F2 적용 의미 변화 자료
- `tutor/data/study_whitelist.json` — F5 학습 화이트리스트
- `tutor/data/court_cases_data.json` — S6 통합 (758→976건)
- `data/phase3_staging/` — S2-A 6법령 본문/연혁
- (별도 리포) `판례조회-AI도구/판례_통합_phase3.txt` — S6 신규 형사 판례 218건

## Phase 3 진행 상태 요약 (자세한 건 `PHASE3_STATUS.md`)

**2026-05-21 갱신** — 오늘 master에 11커밋 push.

- ✅ 완료 (11개): **F1·F2·F3·F4·F5·F6 + S1-A·S2-A·S4(staging)·S6·S7**
- 🟡 부분 완료: **S3-1-a/b** (코드 통합, tlspc 시범 후 롤백)
- 🔴 다음 세션 진입점: **S3-1-b-4** (viewer.html JS multi-law 분기 보강, 1-2시간)
- ⏳ 후속: S5 schedule 마이그레이션 → S8 B3 슬롯
