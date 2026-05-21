"""
S7 효과 테스트 — 안전띠(제50조) 카드 1장 강제 생성
====================================================
build_card를 직접 호출해 schedule.json 영향 없이 단일 카드 생성.
history_evolution 필드가 의도대로 채워지는지 확인.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# 메인 프로젝트 모듈 임포트
sys.path.insert(0, r"c:\Users\user\projects\도로교통법-한눈에-tutor\tutor")
from build_tutor_content import load_indexes, build_card

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
OUT_DIR = ROOT_DIR / "data"

# 테스트 대상 — 안전띠(제50조)
TARGET_JO = "50"
TARGET_DATE = datetime(2026, 6, 15)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if not os.getenv("GEMINI_API_KEY", "").strip():
        print("[ERR] GEMINI_API_KEY 없음", flush=True)
        sys.exit(1)

    print(f"=== S7 효과 테스트 — 제{TARGET_JO}조 카드 생성 ===", flush=True)
    idx = load_indexes()
    articles = idx.get("articles", {})
    info = articles.get(TARGET_JO, {})
    if not info:
        print(f"  [WARN] 제{TARGET_JO}조가 풀에 없음 — basis 정보 약함", flush=True)

    selection = {
        "jo": TARGET_JO,
        "info": info,
        "basis": {
            "weight_score": info.get("weight_score", 0),
            "category": (info.get("categories") or ["특정 운전자의 준수사항"])[0],
            "admin_case_count": info.get("admin_case_count", 0),
            "court_case_count": info.get("court_case_count", 0),
        },
    }
    print(f"  선택 정보: w={selection['basis']['weight_score']}, "
          f"category={selection['basis']['category']}", flush=True)

    card = build_card(selection, idx,
                      target_date=TARGET_DATE.strftime("%Y%m%d"),
                      use_llm=True)

    out = {
        "_test_meta": {
            "target_jo": TARGET_JO,
            "target_date": TARGET_DATE.strftime("%Y-%m-%d"),
            "generated_at": datetime.now().isoformat(),
        },
        "card": card,
    }
    out_path = OUT_DIR / f"_test_card_s7_제{TARGET_JO}조.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[SAVE] {out_path.name}", flush=True)

    # 핵심 결과 출력
    lc = card.get("learning_content")
    print(f"\n=== llm_status: {card.get('llm_status')} ===", flush=True)
    if lc:
        print(f"\noneliner: {lc.get('oneliner')}", flush=True)
        print(f"\nexplanation: {lc.get('explanation')}", flush=True)
        print(f"\n*** history_evolution: ***", flush=True)
        print(f"  {lc.get('history_evolution', '(empty)')}", flush=True)
        print(f"\nteaching_application: {lc.get('teaching_application')}", flush=True)
    elif card.get("llm_note"):
        print(f"  Note: {card.get('llm_note')}", flush=True)


if __name__ == "__main__":
    main()
