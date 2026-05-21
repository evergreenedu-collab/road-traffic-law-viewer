"""
S7 시제품 — history_evolution 필드 LLM 컨텍스트 구성
=====================================================
F2 적용된 meaningful_diffs.json에서 특정 조문의 현행 의미 변화만 추출,
카드 LLM 프롬프트에 들어갈 [조문 연혁 변화] 섹션을 구성한다.

격리 dir에서 시제품. 메인 코드는 안 건드림.
출력: 조문별 컨텍스트 문자열 (사용자 검토용).
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
DATA_DIR = ROOT_DIR / "data"

DIFFS_PATH = DATA_DIR / "meaningful_diffs.json"
ARTICLES_PATH = Path(
    r"c:\Users\user\projects\도로교통법-한눈에-tutor\tutor\data\index_law_articles.json"
)
HISTORY_PATH = Path(
    r"c:\Users\user\projects\도로교통법-한눈에-tutor\tutor\data\index_law_history.json"
)

# 안전띠·교차로·음주 등 검증 대상
SAMPLE_JOS = ["50", "44", "25", "12", "12의2", "5의3"]

# LLM에 넘길 변화 수 — 카드 1장당 너무 많으면 노이즈
MAX_CHANGES_PER_ARTICLE = 8
# 각 변화 본문 슬라이스 (이전·이후 각각)
SLICE_LEN = 250


def fmt_date(yyyymmdd):
    """공포일자 YYYYMMDD → 'YYYY.MM.DD'."""
    s = re.sub(r"\D", "", str(yyyymmdd or ""))
    if len(s) == 8:
        return f"{s[:4]}.{s[4:6]}.{s[6:8]}"
    return yyyymmdd or "?"


def build_history_section(jo, diffs, current_article_text):
    """카드 LLM 컨텍스트의 [조문 연혁 변화] 섹션 구성."""
    if not diffs:
        return None
    # 최신순으로 정렬 (공포일자 desc)
    sorted_diffs = sorted(diffs, key=lambda r: r.get("공포일자", ""), reverse=True)
    selected = sorted_diffs[:MAX_CHANGES_PER_ARTICLE]

    lines = [f"[조문 연혁 변화 — 제{jo}조 의미 있는 변화 {len(selected)}건]"]
    for r in selected:
        date = fmt_date(r.get("공포일자"))
        change_type = r.get("변경유형", "")
        added = r.get("주요추가", []) or []
        removed = r.get("주요삭제", []) or []
        before = (r.get("샘플_이전_300") or "")[:SLICE_LEN]
        after = (r.get("샘플_이후_300") or "")[:SLICE_LEN]

        lines.append(f"\n• {date} {change_type}")
        if added:
            lines.append(f"  추가어: {', '.join(added[:5])}")
        if removed:
            lines.append(f"  삭제어: {', '.join(removed[:5])}")
        if before:
            lines.append(f"  이전: {before}")
        if after:
            lines.append(f"  이후: {after}")
    return "\n".join(lines)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    diffs_data = json.loads(DIFFS_PATH.read_text(encoding="utf-8"))
    arts = json.loads(ARTICLES_PATH.read_text(encoding="utf-8")).get("조문별", {})
    law_diffs = diffs_data.get("법률", {})

    print(f"=== S7 시제품 — 조문 연혁 변화 컨텍스트 ===")
    print(f"입력: meaningful_diffs.json 법률 {len(law_diffs)}개 조문")
    print(f"      샘플 조문: {SAMPLE_JOS}")

    out = {}
    for jo in SAMPLE_JOS:
        diffs = law_diffs.get(jo, [])
        article_text = arts.get(jo, "")
        section = build_history_section(jo, diffs, article_text)
        if section:
            out[jo] = section
            print(f"\n{'=' * 60}")
            print(section[:2000])  # 콘솔 출력은 2000자 제한
            print(f"  ... (총 {len(section)}자)")

    # JSON으로도 저장 (사용자 검토용)
    out_path = DATA_DIR / "_s7_prototype_contexts.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[SAVE] {out_path.name}")


if __name__ == "__main__":
    main()
