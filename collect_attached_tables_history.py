"""
별표 시점별 본문 수집기
=======================
시행령/시행규칙의 모든 공포일 시점별로 별표 본문을 수집한다.
법령 본문 API 응답의 <별표단위> 태그에 별표 본문이 포함되어 있어 추가 호출 없이 추출 가능하나,
attached_tables.json은 최신 스냅샷만 가지고 있어 변경 이력 추적이 불가했다.
이 스크립트가 시점별 본문을 모아 별표 변경 이력 추적 기반을 제공한다.

사용법:
    python collect_attached_tables_history.py

출력:
    data/attached_tables_history.json
    {
      "시행령": {
        "별표 1": {
          "20260219": {"제목": "...", "내용": "...", "PDF_URL": "...", "HWP_URL": "..."},
          "20251202": {"제목": "...", "내용": "...", "PDF_URL": "...", "HWP_URL": "..."},
          ...
        },
        ...
      },
      "시행규칙": {...}
    }
"""

import json
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import requests

from api_utils import request_xml_with_retry

API_KEY = "evergreen_edu"
DETAIL_URL = "http://www.law.go.kr/DRF/lawService.do"
REQUEST_DELAY = 0.6
SAVE_INTERVAL = 20

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
HISTORY_PATH = os.path.join(DATA_DIR, "article_history.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "attached_tables_history.json")
CHECKPOINT_PATH = os.path.join(DATA_DIR, "attached_tables_history_checkpoint.json")


def safe_text(el, tag):
    e = el.find(tag)
    return (e.text or "").strip() if (e is not None and e.text) else ""


def fetch_tables(mst):
    """MST의 별표 본문 + PDF URL + HWP URL 추출. {별표명: {제목, 내용, PDF_URL, HWP_URL}}

    API 응답의 두 다운로드 링크 태그:
      <별표서식파일링크>     → HWP 다운로드 URL  (옛 이름 — 사실 HWP를 가리킴)
      <별표서식PDF파일링크>  → PDF 다운로드 URL
    """
    params = {"OC": API_KEY, "target": "law", "type": "XML", "MST": mst}
    resp = request_xml_with_retry(DETAIL_URL, params, timeout=60)
    if resp is None:
        raise RuntimeError(f"본문 조회 최종 실패 (MST={mst})")
    root = ET.fromstring(resp.text)

    tables = {}
    for unit in root.findall(".//별표단위"):
        구분 = safe_text(unit, "별표구분")
        번호 = safe_text(unit, "별표번호")
        가지 = safe_text(unit, "별표가지번호")
        제목 = safe_text(unit, "별표제목")
        내용 = safe_text(unit, "별표내용")
        pdf_link = safe_text(unit, "별표서식PDF파일링크")
        hwp_link = safe_text(unit, "별표서식파일링크")

        if not 번호:
            continue

        num_str = str(int(번호)) if 번호.isdigit() else 번호
        if 가지 and 가지 != "00":
            sub = str(int(가지)) if 가지.isdigit() else 가지
            num_str += f"의{sub}"
        prefix = 구분 if 구분 else "별표"
        key = f"{prefix} {num_str}"

        tables[key] = {"제목": 제목, "내용": 내용, "PDF_URL": pdf_link, "HWP_URL": hwp_link}
    return tables


def main():
    print("=" * 60)
    print("  별표 시점별 본문 수집")
    print("=" * 60)

    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        hist = json.load(f)

    # 체크포인트
    result = {"시행령": {}, "시행규칙": {}}
    done = set()
    if os.path.exists(CHECKPOINT_PATH):
        with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
            ckpt = json.load(f)
        result = ckpt.get("data", result)
        done = set(ckpt.get("done", []))
        print(f"🔄 체크포인트 발견 (완료 {len(done)}건)")

    for law_type in ["시행령", "시행규칙"]:
        versions = hist["법령"].get(law_type, {}).get("버전", [])
        # 같은 공포일자 다중 버전 → 첫 번째만
        seen_pubs = set()
        unique_versions = []
        for v in versions:
            mst = v.get("MST", "")
            pub = v.get("공포일자", "")
            if not mst or not pub or pub in seen_pubs:
                continue
            seen_pubs.add(pub)
            unique_versions.append(v)

        print(f"\n📖 {law_type}: {len(unique_versions)}개 시점")
        for i, ver in enumerate(unique_versions):
            mst = ver["MST"]
            pub = ver["공포일자"]
            ckpt_key = f"{law_type}/{mst}"
            if ckpt_key in done:
                continue
            print(f"  [{i+1}/{len(unique_versions)}] {pub[:4]}.{pub[4:6]}.{pub[6:]} (MST={mst})")

            time.sleep(REQUEST_DELAY)
            try:
                tables = fetch_tables(mst)
                for tname, tdata in tables.items():
                    if tname not in result[law_type]:
                        result[law_type][tname] = {}
                    result[law_type][tname][pub] = tdata
                done.add(ckpt_key)
            except Exception as e:
                print(f"    ❌ 오류: {e}")

            if (i + 1) % SAVE_INTERVAL == 0:
                with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
                    json.dump({"data": result, "done": sorted(done)}, f, ensure_ascii=False)
                print(f"    💾 중간 저장")

    # 최종 저장
    final = {
        "생성일시": datetime.now().isoformat(),
        "설명": "시행령/시행규칙 공포일 시점별 별표 본문",
        "시행령": result["시행령"],
        "시행규칙": result["시행규칙"],
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False)
    size_mb = os.path.getsize(OUTPUT_PATH) / (1024 * 1024)
    print(f"\n💾 저장: {OUTPUT_PATH} ({size_mb:.1f}MB)")

    # 통계
    for t in ["시행령", "시행규칙"]:
        n_tables = len(result[t])
        n_versions = sum(len(v) for v in result[t].values())
        print(f"  {t}: {n_tables}개 별표/서식, {n_versions}개 시점 본문")

    if os.path.exists(CHECKPOINT_PATH):
        os.remove(CHECKPOINT_PATH)


if __name__ == "__main__":
    main()
