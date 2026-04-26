"""
조문 전후비교 데이터 구축
===========================
각 법령의 조문별로 실제 텍스트가 변경된 시점을 찾아
이전/이후 텍스트 쌍을 만듭니다.

사용법:
    python build_text_diff.py

출력:
    - data/text_diff.json (조문별 전후비교 데이터)
"""

import json
import os
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
HISTORY_PATH = os.path.join(DATA_DIR, "article_history.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "text_diff.json")


def get_full_text(jo_data):
    """조문내용 + 항내용을 합친 전체 텍스트 (원문자 중복 제거, 줄 정규화)"""
    import re
    content = jo_data.get("조문내용", "") or ""
    for p in jo_data.get("항", []):
        h_content = p.get("항내용", "") or ""
        if h_content:
            content += f"\n{h_content}"
    # 줄 끝 공백 제거 + 연속 공백 정규화
    lines = [re.sub(r'\s+', ' ', line).strip() for line in content.split('\n')]
    return '\n'.join(line for line in lines if line)


def normalize_for_compare(text):
    """비교용 정규화 — 개정이력 태그 제거"""
    import re
    return re.sub(r'<(?:개정|신설|본조신설|전문개정|제목개정)[^>]*>', '', text).strip()


def main():
    print("📖 데이터 로딩...")
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        hist = json.load(f)

    print("=" * 55)
    print("  조문 전후비교 데이터 구축")
    print("=" * 55)

    result = {"생성일시": datetime.now().isoformat(), "법률": {}, "시행령": {}, "시행규칙": {}}

    for law_type in ["법률", "시행령", "시행규칙"]:
        print(f"\n📌 {law_type}...")
        law_data = hist["법령"].get(law_type, {})
        versions = law_data.get("버전", [])

        # 모든 조문키 수집
        all_keys = set()
        for ver in versions:
            for jo_key in ver.get("조문", {}).keys():
                all_keys.add(jo_key)

        diffs = {}  # 조문키 → [{공포일자, 이전, 이후, 변경유형}]
        total_diffs = 0

        for jo_key in all_keys:
            # 이 조문의 모든 버전 텍스트 (공포일 순)
            jo_versions = []
            for ver in versions:
                jo = ver.get("조문", {}).get(jo_key, {})
                full = get_full_text(jo)
                changed = jo.get("조문변경여부") == "Y" or bool(jo.get("조문제개정유형"))
                jo_versions.append({
                    "pub": ver.get("공포일자", ""),
                    "full": full,
                    "changed": changed,
                    "title": jo.get("조문제목", ""),
                    "change_type": jo.get("조문제개정유형", ""),
                })

            jo_versions.sort(key=lambda x: x["pub"])

            # 실제 텍스트가 바뀐 시점 찾기 (개정이력 태그 무시)
            # 신설(첫 등장)도 포함 — 이전="" + 변경유형="신설"
            changes = []
            prev_text = ""
            prev_norm = ""
            for v in jo_versions:
                if not v["full"]:
                    continue
                curr_norm = normalize_for_compare(v["full"])
                if prev_text:
                    # 기존 조문 변경
                    if prev_norm != curr_norm:
                        changes.append({
                            "공포일자": v["pub"],
                            "조문제목": v["title"],
                            "변경유형": v["change_type"] or "개정",
                            "이전": prev_text,
                            "이후": v["full"],
                        })
                        total_diffs += 1
                elif v["changed"]:
                    # 첫 등장 + 변경 표시 → 신설
                    changes.append({
                        "공포일자": v["pub"],
                        "조문제목": v["title"],
                        "변경유형": v["change_type"] or "신설",
                        "이전": "",
                        "이후": v["full"],
                    })
                    total_diffs += 1
                prev_text = v["full"]
                prev_norm = curr_norm

            if changes:
                diffs[jo_key] = changes

        result[law_type] = diffs
        print(f"  ✅ {len(diffs)}개 조문, {total_diffs}건 실제 변경")

    # 저장
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)

    size_mb = os.path.getsize(OUTPUT_PATH) / (1024 * 1024)
    print(f"\n💾 저장: {OUTPUT_PATH} ({size_mb:.1f}MB)")


if __name__ == "__main__":
    main()
