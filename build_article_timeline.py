"""
조문별 변경 타임라인 구축
===========================
article_history.json에서 각 조문의 변경 이력을 추출하고,
법률↔시행령↔시행규칙 캐스케이드 연결을 만듭니다.

사용법:
    python build_article_timeline.py

출력:
    - data/article_timeline.json (뷰어용 요약 타임라인)
"""

import json
import os
import re
from datetime import datetime, timedelta
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")

HISTORY_PATH = os.path.join(DATA_DIR, "article_history.json")
MAP_PATH = os.path.join(DATA_DIR, "three_tier_map.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "article_timeline.json")


def parse_date(s):
    try:
        return datetime.strptime(s[:8], "%Y%m%d")
    except (ValueError, TypeError):
        return None


def main():
    print("📖 데이터 로딩...")
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        hist = json.load(f)
    with open(MAP_PATH, "r", encoding="utf-8") as f:
        mapdata = json.load(f)

    print("=" * 55)
    print("  조문별 변경 타임라인 구축")
    print("=" * 55)

    # =====================================================
    # 1단계: 법령 전체 연혁 타임라인 (레벨 1)
    # =====================================================
    print("\n📌 1단계: 법령 전체 연혁 타임라인...")

    law_timeline = []  # [{공포일자, 법령유형, 제개정구분, 제개정이유(앞200), 변경조문수, 변경조문키[], 연쇄개정[]}]

    for law_type in ["법률", "시행령", "시행규칙"]:
        law_data = hist["법령"].get(law_type, {})
        for ver in law_data.get("버전", []):
            pub = ver.get("공포일자", "")
            if not pub:
                continue
            entry = {
                "법령유형": law_type,
                "공포일자": pub,
                "시행일자": ver.get("시행일자", ""),
                "제개정구분": ver.get("제개정구분", ""),
                "제개정이유": (ver.get("제개정이유", "") or "")[:300],
                "변경조문수": ver.get("변경조문수", 0),
                "변경조문키": ver.get("변경조문키", []),
            }
            law_timeline.append(entry)

    # 공포일 기준 정렬
    law_timeline.sort(key=lambda x: x["공포일자"], reverse=True)

    # 연쇄 개정 매칭 (공포일 90일 이내)
    THRESHOLD = 90
    for entry in law_timeline:
        pub_dt = parse_date(entry["공포일자"])
        if not pub_dt:
            continue
        cascade = []
        for other in law_timeline:
            if other["법령유형"] == entry["법령유형"]:
                continue
            other_dt = parse_date(other["공포일자"])
            if not other_dt:
                continue
            diff = abs((pub_dt - other_dt).days)
            if diff <= THRESHOLD:
                cascade.append({
                    "법령유형": other["법령유형"],
                    "공포일자": other["공포일자"],
                    "제개정구분": other["제개정구분"],
                    "일자차이": diff,
                })
        if cascade:
            cascade.sort(key=lambda x: x["일자차이"])
            entry["연쇄개정"] = cascade

    print(f"  ✅ {len(law_timeline)}건 (연쇄 매칭 {sum(1 for e in law_timeline if e.get('연쇄개정'))}건)")

    # =====================================================
    # 2단계: 조문별 변경 타임라인 (레벨 2)
    # =====================================================
    print("\n📌 2단계: 조문별 변경 타임라인...")

    # 법률 조문별로 변경 이력 수집
    article_timelines = {}  # {법령유형: {조문키: [{공포일자, 변경유형, 조문내용, ...}]}}

    for law_type in ["법률", "시행령", "시행규칙"]:
        article_timelines[law_type] = defaultdict(list)
        law_data = hist["법령"].get(law_type, {})

        for ver in law_data.get("버전", []):
            pub = ver.get("공포일자", "")
            eff = ver.get("시행일자", "")
            rev = ver.get("제개정구분", "")
            reason = (ver.get("제개정이유", "") or "")[:300]

            for jo_key, jo_data in ver.get("조문", {}).items():
                changed = jo_data.get("조문변경여부") == "Y" or bool(jo_data.get("조문제개정유형"))
                if not changed:
                    continue

                change_entry = {
                    "공포일자": pub,
                    "시행일자": eff,
                    "제개정구분": rev,
                    "변경유형": jo_data.get("조문제개정유형", ""),
                    "조문제목": jo_data.get("조문제목", ""),
                    "조문내용": jo_data.get("조문내용", ""),
                    "제개정이유": reason,
                    "항": jo_data.get("항", []),
                }
                article_timelines[law_type][jo_key].append(change_entry)

        # 각 조문 내 공포일 기준 정렬 (최신 먼저)
        for jo_key in article_timelines[law_type]:
            article_timelines[law_type][jo_key].sort(
                key=lambda x: x["공포일자"], reverse=True
            )

    # 중복 제거 (같은 공포일+같은 조문내용)
    for law_type in article_timelines:
        for jo_key in article_timelines[law_type]:
            entries = article_timelines[law_type][jo_key]
            deduped = []
            seen = set()
            for e in entries:
                key = (e["공포일자"], (e["조문내용"] or "")[:50])
                if key not in seen:
                    seen.add(key)
                    deduped.append(e)
            article_timelines[law_type][jo_key] = deduped

    # 통계
    for law_type in ["법률", "시행령", "시행규칙"]:
        tl = article_timelines[law_type]
        total_articles = len(tl)
        total_changes = sum(len(v) for v in tl.values())
        print(f"  {law_type}: {total_articles}개 조문, {total_changes}건 변경")

    # =====================================================
    # 3단계: 법률 조문 ↔ 하위법령 조문 연혁 연결
    # =====================================================
    print("\n📌 3단계: 법률↔하위법령 조문 연혁 연결...")

    # 매핑 데이터에서 법률 조문 → 연결된 시행령/시행규칙 조문 키 추출
    law_to_sub = {}  # 법률조키 → {시행령: [조키], 시행규칙: [조키]}
    for entry in mapdata["매핑"]:
        jo_key = entry["법률_조키"]
        linked_decree = set()
        linked_rule = set()

        # 항별 매핑
        for pm in entry.get("항별_매핑", []):
            for d in pm.get("시행령", []):
                linked_decree.add(d["조키"])
            for r in pm.get("시행규칙_직접", []):
                linked_rule.add(r["조키"])
            for d in pm.get("시행령", []):
                for r in d.get("시행규칙", []):
                    linked_rule.add(r["조키"])

        # 조문전체 매핑
        for g in entry.get("조문전체_매핑", []):
            if g["법령유형"] == "시행령":
                linked_decree.add(g["조키"])
            elif g["법령유형"] == "시행규칙":
                linked_rule.add(g["조키"])

        if linked_decree or linked_rule:
            law_to_sub[jo_key] = {
                "시행령": sorted(linked_decree),
                "시행규칙": sorted(linked_rule),
            }

    print(f"  ✅ {len(law_to_sub)}개 법률 조문에 하위법령 연결")

    # =====================================================
    # 저장
    # =====================================================
    result = {
        "생성일시": datetime.now().isoformat(),
        "법령전체연혁": law_timeline,
        "조문별연혁": {
            "법률": {k: v for k, v in article_timelines["법률"].items()},
            "시행령": {k: v for k, v in article_timelines["시행령"].items()},
            "시행규칙": {k: v for k, v in article_timelines["시행규칙"].items()},
        },
        "법률_하위법령_연결": law_to_sub,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)

    size_mb = os.path.getsize(OUTPUT_PATH) / (1024 * 1024)
    print(f"\n💾 저장: {OUTPUT_PATH} ({size_mb:.1f}MB)")


if __name__ == "__main__":
    main()
