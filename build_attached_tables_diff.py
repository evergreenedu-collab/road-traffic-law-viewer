"""
별표 전후비교(변경 이력) 데이터 구축
======================================
collect_attached_tables_history.py가 모은 시점별 별표 본문을
인접 시점끼리 비교하여 변경 시점과 이전/이후 본문 쌍을 만든다.

사용법:
    python build_attached_tables_diff.py

출력:
    data/attached_tables_diff.json
    {
      "시행령": {
        "별표 1": [{"공포일자": "...", "이전": "...", "이후": "...", "변경유형": "신설|개정"}, ...],
        ...
      },
      "시행규칙": {...}
    }
"""

import json
import os
import re
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
INPUT_PATH = os.path.join(DATA_DIR, "attached_tables_history.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "attached_tables_diff.json")


def normalize_for_compare(text):
    """비교용 정규화 — 개정이력 태그 제거 + 공백 정규화"""
    if not text:
        return ""
    t = re.sub(r"<(?:개정|신설|본조신설|전문개정|제목개정)[^>]*>", "", text)
    # 줄 단위 공백 정규화
    lines = [re.sub(r"\s+", " ", line).strip() for line in t.split("\n")]
    return "\n".join(line for line in lines if line)


def main():
    print("=" * 60)
    print("  별표 전후비교 데이터 구축")
    print("=" * 60)

    if not os.path.exists(INPUT_PATH):
        raise FileNotFoundError(
            f"{INPUT_PATH} 없음. 먼저 collect_attached_tables_history.py를 실행하세요."
        )
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        history = json.load(f)

    result = {"생성일시": datetime.now().isoformat(), "시행령": {}, "시행규칙": {}}

    for law_type in ["시행령", "시행규칙"]:
        print(f"\n📌 {law_type}...")
        n_tables = 0
        n_changes = 0
        for tname, by_pub in history.get(law_type, {}).items():
            # 공포일 순으로 정렬
            sorted_pubs = sorted(by_pub.items(), key=lambda x: x[0])
            changes = []
            prev_text = ""
            prev_norm = ""
            prev_pdf_url = ""
            prev_pub = ""
            for pub, tdata in sorted_pubs:
                full = tdata.get("내용", "") or ""
                pdf_url = tdata.get("PDF_URL", "") or ""
                if not full:
                    continue
                curr_norm = normalize_for_compare(full)
                if prev_text:
                    if prev_norm != curr_norm:
                        changes.append({
                            "공포일자": pub,
                            "별표명": tname,
                            "제목": tdata.get("제목", ""),
                            "변경유형": "개정",
                            "이전": prev_text,
                            "이후": full,
                            "이전PDF_URL": prev_pdf_url,
                            "이후PDF_URL": pdf_url,
                            "이전공포일": prev_pub,
                        })
                        n_changes += 1
                else:
                    changes.append({
                        "공포일자": pub,
                        "별표명": tname,
                        "제목": tdata.get("제목", ""),
                        "변경유형": "신설",
                        "이전": "",
                        "이후": full,
                        "이전PDF_URL": "",
                        "이후PDF_URL": pdf_url,
                        "이전공포일": "",
                    })
                    n_changes += 1
                prev_text = full
                prev_norm = curr_norm
                prev_pdf_url = pdf_url
                prev_pub = pub
            if changes:
                result[law_type][tname] = changes
                n_tables += 1
        print(f"  ✅ {n_tables}개 별표/서식, {n_changes}건 변경 시점")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    size_mb = os.path.getsize(OUTPUT_PATH) / (1024 * 1024)
    print(f"\n💾 저장: {OUTPUT_PATH} ({size_mb:.1f}MB)")


if __name__ == "__main__":
    main()
