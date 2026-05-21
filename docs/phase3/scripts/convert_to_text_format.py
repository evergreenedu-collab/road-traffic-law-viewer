"""
S6 정식 통합 — extra_court_cases_data.json → 판례_통합 텍스트 형식
====================================================================
build_indexes.py의 parse_court_cases가 인식하는 형식으로 218건 변환.
glob 'judgment_통합*.txt'(실제로는 '판례_통합*.txt')이 자동 인식 →
build_indexes.py 재실행 시 자동으로 인덱스에 포함됨.

출력: 판례조회-AI도구/판례_통합_phase3.txt
"""

import json
import re
from pathlib import Path

EXTRA = Path(r"c:\Users\user\projects\overnight_phase3\data\extra_court_cases_data.json")
OUT = Path(r"c:\Users\user\projects\판례조회-AI도구\판례_통합_phase3.txt")
SEP = "━" * 49


def normalize_date(d):
    """선고일자 YYYYMMDD → YYYY.MM.DD."""
    if not d:
        return ""
    s = re.sub(r"\D", "", str(d))
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}.{s[4:6]}.{s[6:8]}"
    return d


def extract_ruling(raw):
    """fetch된 ruling 본문에서 파서가 인식하는 [판결요지] 보장.
    원본은 '[판시사항] ... [판결요지] ... [전문] ...' 형식.
    [판결요지]가 없으면 [판시사항] 또는 [전문] 본문을 그대로 [판결요지]로."""
    if "[판결요지]" in raw:
        return raw
    # [판시사항]만 있으면 [판결요지] 마커 추가 (파서 호환)
    if "[판시사항]" in raw and "[전문]" in raw:
        return raw.replace("[전문]", "[판결요지]\n[전문]", 1)
    if "[판시사항]" in raw:
        return raw.replace("[판시사항]", "[판결요지]\n[판시사항]", 1)
    if "[전문]" in raw:
        return raw.replace("[전문]", "[판결요지]\n[전문]", 1)
    # 아예 마커가 없으면 [판결요지] 추가
    return f"[판결요지]\n{raw}"


def main():
    data = json.loads(EXTRA.read_text(encoding="utf-8"))
    items = data.get("데이터", {})
    print(f"[READ] {EXTRA.name}: {len(items)}건")

    lines = []
    lines.append("# 판례 통합 — Phase 3 추가 (2026-05-21)")
    lines.append("# 교특법·도주차량·위험운전치사상·특가법(교통) 신규 218건")
    lines.append("")

    written = 0
    for i, (key, v) in enumerate(items.items(), 1):
        case_name = v.get("case_name", "").strip()
        case_no = v.get("case_no", "").strip()
        date = normalize_date(v.get("date", ""))
        court = v.get("court", "").strip()
        ruling = extract_ruling(v.get("ruling", "") or "")
        if not case_no:
            continue

        lines.append(SEP)
        lines.append(f"【{i}】 {case_name}")
        lines.append(f"선고일: {date} | {court}")
        lines.append(f"사건번호: {case_no}")
        lines.append("")
        lines.append(ruling)
        lines.append("")
        written += 1

    OUT.write_text("\n".join(lines), encoding="utf-8")
    size_kb = OUT.stat().st_size / 1024
    print(f"[SAVE] {OUT} ({size_kb:.0f}KB, {written}건)")
    print(f"\n다음: cd 도로교통법-한눈에-tutor && py tutor/build_indexes.py")


if __name__ == "__main__":
    main()
