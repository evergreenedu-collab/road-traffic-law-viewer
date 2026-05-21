"""
S6 통합 — 218건 신규 판례를 court_cases_data.json에 병합
================================================================
- 기존 court_cases_data.json 백업 (.bak.{timestamp})
- extra_court_cases_data.json의 데이터를 병합 (case_no 키, 충돌 시 기존 우선)
- 메타 갱신 (판례수, 생성일시, 출처 추가)
- index_cases 재빌드는 별도 (build_indexes.py 실행 권장)

사용자가 직접 결정한 통합 작업. 격리 원칙은 일시 해제 (백업으로 안전성 확보).
"""

import json
import shutil
import time
from pathlib import Path

TUTOR_DATA = Path(r"c:\Users\user\projects\도로교통법-한눈에-tutor\tutor\data")
EXTRA = Path(r"c:\Users\user\projects\overnight_phase3\data\extra_court_cases_data.json")
TARGET = TUTOR_DATA / "court_cases_data.json"


def main():
    if not TARGET.exists():
        print(f"[ERR] {TARGET} 없음")
        return
    if not EXTRA.exists():
        print(f"[ERR] {EXTRA} 없음")
        return

    ts = time.strftime("%Y%m%d_%H%M%S")
    backup = TARGET.with_suffix(f".bak.{ts}.json")
    shutil.copy2(TARGET, backup)
    print(f"[BACKUP] {backup.name}")

    base = json.loads(TARGET.read_text(encoding="utf-8"))
    extra = json.loads(EXTRA.read_text(encoding="utf-8"))

    base_data = base.get("데이터", {})
    extra_data = extra.get("데이터", {})

    before = len(base_data)
    conflict = 0
    added = 0
    for k, v in extra_data.items():
        if k in base_data:
            conflict += 1
            continue   # 기존 우선
        # 신규 데이터의 필드를 기존 스키마(case_name/date/court/case_no/ruling)로 매핑
        base_data[k] = {
            "case_name": v.get("case_name", ""),
            "date": v.get("date", ""),
            "court": v.get("court", ""),
            "case_no": v.get("case_no", k),
            "ruling": v.get("ruling", ""),
            "_source": "phase3_overnight",
            "_검색쿼리": v.get("_검색쿼리", ""),
            "_사건종류명": v.get("case_kind", ""),
            "_판결유형": v.get("ruling_type", ""),
            "_참조조문": v.get("참조조문", ""),
            "_참조판례": v.get("참조판례", ""),
            "_판례일련번호": v.get("판례일련번호", ""),
        }
        added += 1
    after = len(base_data)

    base["데이터"] = base_data
    base["판례수"] = after
    base["생성일시"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    base["설명"] = (base.get("설명", "") + f" + Phase 3 overnight 추가 {added}건").strip()
    base["_phase3_merge"] = {
        "백업": backup.name,
        "이전_건수": before,
        "신규_추가": added,
        "충돌_스킵": conflict,
        "현재_건수": after,
    }

    TARGET.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[MERGE] before={before}, added={added}, conflict={conflict}, after={after}")
    print(f"[SAVE] {TARGET}")
    print(f"\n다음 단계: 인덱스 재빌드")
    print(f"  cd c:\\Users\\user\\projects\\도로교통법-한눈에-tutor")
    print(f"  py tutor/build_indexes.py")


if __name__ == "__main__":
    main()
