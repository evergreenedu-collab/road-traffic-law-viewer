"""
도로교통법 조문별 변경 이력 수집기
====================================
3개 법령의 모든 과거 버전에서 각 조문의 변경 여부와 내용을 추출합니다.

사용법:
    python collect_article_history.py

출력:
    - data/article_history.json (조문별 변경 이력)
"""

import requests
import xml.etree.ElementTree as ET
import json
import os
import re
import time
from datetime import datetime

from api_utils import request_xml_with_retry

API_KEY = "evergreen_edu"
DETAIL_URL = "http://www.law.go.kr/DRF/lawService.do"
HISTORY_LIST_URL = "https://www.law.go.kr/LSW/lsHstListR.do"
REQUEST_DELAY = 0.6
SAVE_INTERVAL = 20  # 중간 저장 간격

# 법령ID → MST 목록 조회용
LAW_GROUP = [
    {"유형": "법률",     "법령명": "도로교통법",         "법령ID": "001638"},
    {"유형": "시행령",   "법령명": "도로교통법 시행령",   "법령ID": "003395"},
    {"유형": "시행규칙", "법령명": "도로교통법 시행규칙", "법령ID": "007079"},
]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")


def safe_text(el, tag):
    e = el.find(tag)
    if e is not None and e.text:
        return e.text.strip()
    return ""


def make_article_key(jo_num, jo_sub):
    key = str(jo_num)
    if jo_sub and jo_sub != "0":
        key += f"의{jo_sub}"
    return key


def fetch_history_list(law_id, law_name):
    """법제처 웹에서 전체 연혁 MST 목록을 가져옵니다."""
    print(f"\n📋 [{law_name}] 연혁 목록 조회...")
    params = {"lsId": law_id}
    resp = request_xml_with_retry(HISTORY_LIST_URL, params, timeout=30)
    if resp is None:
        print(f"  ❌ 연혁 목록 조회 실패")
        return []

    pattern = r"lsViewLsHst2\('(\d+)',\s*'(\d+)',\s*'(\d+)',\s*'(\d+)',\s*'[^']*',\s*'[^']*'\s*,\s*'([^']*)'\)"
    matches = re.findall(pattern, resp.text)

    seen = set()
    items = []
    for mst, pub_date, pub_no, eff_date, rev_type in matches:
        key = (mst, eff_date)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "MST": mst,
            "공포일자": pub_date,
            "공포번호": pub_no,
            "시행일자": eff_date,
            "제개정구분": rev_type,
        })

    print(f"  ✅ {len(items)}건")
    return sorted(items, key=lambda x: x["공포일자"], reverse=True)


def fetch_version_articles(mst):
    """특정 버전의 모든 조문에서 변경 정보를 추출합니다."""
    params = {"OC": API_KEY, "target": "law", "type": "XML", "MST": mst}
    resp = request_xml_with_retry(DETAIL_URL, params, timeout=60)
    if resp is None:
        raise RuntimeError(f"본문 조회 최종 실패 (MST={mst})")
    root = ET.fromstring(resp.text)

    basic = root.find(".//기본정보")
    if basic is None:
        basic = root
    info = {
        "법령명": safe_text(basic, "법령명_한글") or safe_text(basic, "법령명한글"),
        "공포일자": safe_text(basic, "공포일자"),
        "시행일자": safe_text(basic, "시행일자"),
        "제개정구분": safe_text(basic, "제개정구분"),
    }

    # 제개정이유
    reason = safe_text(root, "제개정이유내용")
    if not reason:
        reason_el = root.find(".//제개정이유")
        if reason_el is not None:
            reason = safe_text(reason_el, "제개정이유내용") or (reason_el.text or "").strip()
    info["제개정이유"] = reason

    # 조문별 변경 정보 추출
    articles = {}
    for jo in root.findall(".//조문단위"):
        jo_type = safe_text(jo, "조문여부")
        if jo_type != "조문":
            continue

        jo_num = safe_text(jo, "조문번호")
        jo_sub = safe_text(jo, "조문가지번호")
        if not jo_num:
            continue

        jo_key = make_article_key(jo_num, jo_sub)
        title = safe_text(jo, "조문제목")
        content = safe_text(jo, "조문내용")
        change_flag = safe_text(jo, "조문변경여부")
        change_type = safe_text(jo, "조문제개정유형")
        eff_date = safe_text(jo, "조문시행일자")

        # 항 + 호 내용 수집
        paras = []
        for hang in jo.findall(".//항"):
            h_num = safe_text(hang, "항번호")
            h_content = safe_text(hang, "항내용")
            h_change = safe_text(hang, "항제개정유형")

            # 호 파싱 — 벌칙 등 "각 호" 조문은 내용이 전부 호에 들어있음
            sub_items = []
            for ho in hang.findall(".//호"):
                ho_content = safe_text(ho, "호내용")
                # 목 파싱 — 정의 등 "각 목" 조문은 내용이 목에 들어있음
                mok_items = []
                for mok in ho.findall(".//목"):
                    mok_content = safe_text(mok, "목내용")
                    if mok_content:
                        mok_items.append({
                            "목번호": safe_text(mok, "목번호"),
                            "목내용": mok_content,
                        })
                # 호내용이 있거나 목이 있으면 호 엔트리를 보존
                if ho_content or mok_items:
                    sub_items.append({
                        "호번호": safe_text(ho, "호번호"),
                        "호내용": ho_content,
                        "목": mok_items,
                    })

            # 항내용이 있거나 호가 있으면 항 엔트리를 보존
            if h_content or sub_items:
                paras.append({
                    "항번호": h_num,
                    "항내용": h_content,
                    "항제개정유형": h_change,
                    "호": sub_items,
                })

        articles[jo_key] = {
            "조문제목": title,
            "조문내용": content,
            "조문변경여부": change_flag,
            "조문제개정유형": change_type,
            "조문시행일자": eff_date,
            "항": paras,
        }

    info["조문"] = articles
    return info


def collect_all():
    """3개 법령의 전체 과거 버전에서 조문별 변경 이력을 수집합니다."""
    checkpoint_path = os.path.join(DATA_DIR, "article_history_checkpoint.json")
    output_path = os.path.join(DATA_DIR, "article_history.json")

    print("=" * 55)
    print("  조문별 변경 이력 수집기")
    print("  대상: 도로교통법 / 시행령 / 시행규칙 전체 연혁")
    print("=" * 55)

    # 체크포인트 확인
    result = None
    if os.path.exists(checkpoint_path):
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            result = json.load(f)
        done = sum(len(v.get("버전", [])) for v in result.get("법령", {}).values())
        print(f"\n🔄 체크포인트 발견! (기존 {done}건)")
    else:
        result = {
            "생성일시": datetime.now().isoformat(),
            "설명": "도로교통법 3개 법령의 조문별 변경 이력",
            "법령": {},
        }

    done_types = set(
        k for k, v in result.get("법령", {}).items()
        if v.get("수집완료")
    )

    for law_info in LAW_GROUP:
        law_type = law_info["유형"]
        law_name = law_info["법령명"]
        law_id = law_info["법령ID"]

        if law_type in done_types:
            print(f"\n⏭️ {law_type} — 이미 수집 완료, 건너뜁니다.")
            continue

        print(f"\n{'=' * 55}")
        print(f"📖 {law_type}: {law_name}")
        print(f"{'=' * 55}")

        # 연혁 목록
        history_list = fetch_history_list(law_id, law_name)
        if not history_list:
            continue

        # 이미 수집된 버전 확인
        existing = result["법령"].get(law_type, {}).get("버전", [])
        existing_msts = {v["MST"] for v in existing}

        law_data = result["법령"].get(law_type, {
            "법령유형": law_type,
            "법령명": law_name,
            "전체버전수": len(history_list),
            "버전": existing,
            "수집완료": False,
        })

        for i, ver in enumerate(history_list):
            mst = ver["MST"]
            if mst in existing_msts:
                continue

            pub = ver["공포일자"]
            rev = ver["제개정구분"]
            print(f"  📄 [{i+1}/{len(history_list)}] {pub[:4]}.{pub[4:6]}.{pub[6:]} ({rev}) MST={mst}")

            time.sleep(REQUEST_DELAY)
            try:
                version_data = fetch_version_articles(mst)
                version_data["MST"] = mst

                # 변경된 조문만 요약
                changed = [
                    k for k, v in version_data.get("조문", {}).items()
                    if v.get("조문변경여부") == "Y" or v.get("조문제개정유형")
                ]
                version_data["변경조문수"] = len(changed)
                version_data["변경조문키"] = changed

                law_data["버전"].append(version_data)
            except Exception as e:
                print(f"    ❌ 오류: {e}")
                law_data["버전"].append({
                    "MST": mst,
                    "공포일자": pub,
                    "오류": str(e),
                })

            # 중간 저장
            if (i + 1) % SAVE_INTERVAL == 0:
                result["법령"][law_type] = law_data
                os.makedirs(DATA_DIR, exist_ok=True)
                with open(checkpoint_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False)
                print(f"    💾 중간 저장 ({len(law_data['버전'])}/{len(history_list)})")

        law_data["수집완료"] = True
        result["법령"][law_type] = law_data

        # 법령 완료 시 저장
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        print(f"\n  ✅ {law_name}: {len(law_data['버전'])}건 수집 완료")

    # 최종 저장
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"\n💾 저장: {output_path} ({size_mb:.1f}MB)")

    # 체크포인트 삭제
    if os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)

    # 요약
    print(f"\n{'=' * 55}")
    print("📊 수집 결과 요약")
    print(f"{'=' * 55}")
    for law_type, law_data in result["법령"].items():
        ver_count = len(law_data.get("버전", []))
        total_changed = sum(
            v.get("변경조문수", 0)
            for v in law_data.get("버전", [])
            if isinstance(v.get("변경조문수"), int)
        )
        print(f"  {law_type}: {ver_count}개 버전, 변경 조문 합계 {total_changed}건")


if __name__ == "__main__":
    collect_all()
