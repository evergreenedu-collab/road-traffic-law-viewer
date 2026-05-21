"""
Phase 3 신규 법령 수집 스크립트 (격리판)
==========================================
기존 프로젝트 코드/데이터를 건드리지 않기 위해 `overnight_phase3/` 안에서만 동작.

Codex 검토 반영:
  - 출력 격리: SCRIPT_DIR 기반 절대 경로 강제. 상대경로 사용 금지.
  - API 완전성: 각 호출 결과(실패 포함)를 summary에 명시.
  - 재시도: 백오프 [5,15,45,90,180]초. 최종 실패는 None 반환 + 카운트.
"""

import json
import re
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime
import xml.etree.ElementTree as ET

import requests

API_KEY = "evergreen_edu"
SEARCH_URL = "http://www.law.go.kr/DRF/lawSearch.do"
DETAIL_URL = "http://www.law.go.kr/DRF/lawService.do"
# 전체 연혁 목록 — 웹페이지 HTML 파싱 (lawSearch.do는 현행만 반환)
HISTORY_LIST_URL = "https://www.law.go.kr/LSW/lsHstListR.do"
REQUEST_DELAY = 0.6
TIMEOUT = 60

# 절대경로 강제 — Codex 우려 1 반영
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
assert ROOT_DIR.name == "overnight_phase3", f"격리 위반: ROOT_DIR={ROOT_DIR}"
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

LAWS = {
    "tlspc": "교통사고처리 특례법",
    "tkga": "특정범죄 가중처벌 등에 관한 법률",
    "car_mgmt": "자동차관리법",
    "passenger_transport": "여객자동차 운수사업법",
    "cargo_transport": "화물자동차 운수사업법",
    "crim_proc": "형사소송법",
}

BACKOFF = [5, 15, 45, 90, 180]


def safe_text(el, tag):
    e = el.find(tag) if el is not None else None
    return e.text.strip() if (e is not None and e.text) else ""


def request_xml(url, params):
    last = None
    for i in range(len(BACKOFF) + 1):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT,
                             headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
            if i < len(BACKOFF):
                wait = BACKOFF[i]
                print(f"    [WARN] {type(e).__name__} -> retry in {wait}s", flush=True)
                time.sleep(wait)
            else:
                print(f"    [FAIL] final failure: {last}", flush=True)
                return None
    return None


def search_current(law_name):
    """lawSearch.do로 법령ID·현행 MST 1건 획득 (정확매칭)."""
    print(f"\n[SEARCH-CURRENT] {law_name}", flush=True)
    params = {"OC": API_KEY, "target": "law", "type": "XML",
              "query": law_name, "display": 100, "page": 1}
    r = request_xml(SEARCH_URL, params)
    if r is None:
        return None
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError as e:
        print(f"  [ERR] XML parse: {e}", flush=True)
        return None
    for el in root.findall(".//law"):
        name = safe_text(el, "법령명한글")
        if name != law_name:
            continue
        return {
            "법령ID": safe_text(el, "법령ID"),
            "법령명": name,
            "법령MST": safe_text(el, "법령일련번호"),
            "공포일자": safe_text(el, "공포일자"),
            "공포번호": safe_text(el, "공포번호"),
            "시행일자": safe_text(el, "시행일자"),
            "제개정구분": safe_text(el, "제개정구분명"),
        }
    print(f"  [ERR] no exact-name match", flush=True)
    return None


# Codex 검증 2번 반영: 전체 args 캡처 (단일 값만 잡지 않음)
# 패턴: lsViewLsHst2('MST', '공포일자', '공포번호', '시행일자', 'Y/N', '0', '제개정구분')
HIST_PATTERN = re.compile(
    r"lsViewLsHst2\("
    r"\s*'([^']*)'\s*,"   # 1: MST
    r"\s*'([^']*)'\s*,"   # 2: 공포일자
    r"\s*'([^']*)'\s*,"   # 3: 공포번호
    r"\s*'([^']*)'\s*,"   # 4: 시행일자
    r"\s*'([^']*)'\s*,"   # 5: Y/N
    r"\s*'([^']*)'\s*,"   # 6: 0
    r"\s*'([^']*)'\s*\)"  # 7: 제개정구분
)


def fetch_history_list(law_id, law_name):
    """전체 연혁 목록 — lsHstListR.do HTML 파싱.
    Codex 검증 1·5·6·7 반영: 0매칭 시 명시 실패, 중복제거, UTF-8 강제,
    현행 1건 미달 시 회귀 의심."""
    print(f"[SEARCH-HISTORY] {law_name} (lsId={law_id})", flush=True)
    if not law_id:
        print(f"  [ERR] empty law_id — skip", flush=True)
        return []
    params = {"lsId": law_id}
    last = None
    for i in range(len(BACKOFF) + 1):
        try:
            r = requests.get(HISTORY_LIST_URL, params=params, timeout=30,
                             headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            r.encoding = "utf-8"   # 한글 HTML 디코딩 강제 (Codex 검증 6)
            text = r.text
            break
        except requests.RequestException as e:
            last = e
            if i < len(BACKOFF):
                wait = BACKOFF[i]
                print(f"  [WARN] history page {type(e).__name__} -> retry in {wait}s", flush=True)
                time.sleep(wait)
            else:
                print(f"  [FAIL] history page final: {last}", flush=True)
                return []

    matches = HIST_PATTERN.findall(text)
    if not matches:
        # Codex 검증 1·4 반영: 0매칭은 명시 실패 (페이지 구조 변경·페이지네이션 가능성)
        print(f"  [ERR] zero matches for lsViewLsHst2 — page format may have changed", flush=True)
        # 디버그용 페이지 일부 저장
        (DATA_DIR / f"_debug_history_{law_id}.html").write_text(text[:50000], encoding="utf-8")
        return []
    # 중복 제거 (MST + 시행일자 기준), Codex 검증 5
    seen = set()
    items = []
    for mst, pub_date, pub_no, eff_date, _yn, _zero, rev_type in matches:
        key = (mst, eff_date)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "법령ID": law_id,
            "법령명": law_name,
            "법령MST": mst,
            "공포일자": pub_date,
            "공포번호": pub_no,
            "시행일자": eff_date,
            "제개정구분": rev_type,
        })
    # 시행일자 오름차순 — 오래된 것부터
    items.sort(key=lambda x: (x.get("시행일자", ""), x.get("공포일자", "")))
    print(f"  [OK] {len(items)} historical versions (deduplicated)", flush=True)
    return items


def search_history(law_name):
    """현행 1건 → 법령ID → 전체 연혁 목록. Codex 검증 7: 회귀 가드."""
    current = search_current(law_name)
    if not current:
        return []
    items = fetch_history_list(current["법령ID"], law_name)
    if items and len(items) < 1:
        print(f"  [WARN] regression suspected — fewer than current API", flush=True)
    # 현행이 포함됐는지 확인
    current_mst = current.get("법령MST", "")
    if current_mst and not any(x.get("법령MST") == current_mst for x in items):
        print(f"  [WARN] current MST {current_mst} not in history list — adding manually", flush=True)
        items.append(current)
        items.sort(key=lambda x: (x.get("시행일자", ""), x.get("공포일자", "")))
    return items


def fetch_detail(mst):
    params = {"OC": API_KEY, "target": "law", "type": "XML", "MST": mst}
    r = request_xml(DETAIL_URL, params)
    if r is None:
        return None
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError:
        return None
    out = {
        "기본정보": {
            "법령ID": safe_text(root, ".//기본정보/법령ID"),
            "법령명": safe_text(root, ".//기본정보/법령명한글"),
            "공포일자": safe_text(root, ".//기본정보/공포일자"),
            "공포번호": safe_text(root, ".//기본정보/공포번호"),
            "시행일자": safe_text(root, ".//기본정보/시행일자"),
            "제개정구분": safe_text(root, ".//기본정보/제개정구분"),
            "소관부처": safe_text(root, ".//기본정보/소관부처"),
        },
        "조문": [],
        "부칙": [],
        "제개정이유": safe_text(root, ".//제개정이유/제개정이유내용"),
    }
    for jo in root.findall(".//조문단위"):
        out["조문"].append({
            "조문번호": safe_text(jo, "조문번호"),
            "조문가지번호": safe_text(jo, "조문가지번호"),
            "조문제목": safe_text(jo, "조문제목"),
            "조문시행일자": safe_text(jo, "조문시행일자"),
            "조문제개정유형": safe_text(jo, "조문제개정유형"),
            "조문내용": safe_text(jo, "조문내용"),
        })
    for bc in root.findall(".//부칙단위"):
        out["부칙"].append({
            "부칙공포일자": safe_text(bc, "부칙공포일자"),
            "부칙공포번호": safe_text(bc, "부칙공포번호"),
            "부칙내용": safe_text(bc, "부칙내용"),
        })
    return out


def collect_one(code, name, only_latest=False):
    history = search_history(name)
    if not history:
        return None
    if only_latest:
        history = history[-1:]
    print(f"  [FETCH] body for {len(history)} versions", flush=True)
    fetched = []
    failed_mst = []
    for i, meta in enumerate(history, 1):
        mst = meta.get("법령MST")
        if not mst:
            failed_mst.append({"reason": "no_mst", "meta": meta})
            continue
        d = fetch_detail(mst)
        if d is None:
            failed_mst.append({"reason": "fetch_failed", "법령MST": mst, "공포일자": meta.get("공포일자")})
            continue
        d["_검색메타"] = meta
        fetched.append(d)
        if i % 5 == 0 or i == len(history):
            print(f"    [{i}/{len(history)}] body={len(fetched)} fail={len(failed_mst)}", flush=True)
        time.sleep(REQUEST_DELAY)
    result = {
        "법령코드": code,
        "법령명": name,
        "수집시각": datetime.now().isoformat(),
        "버전수_요청": len(history),
        "버전수_성공": len(fetched),
        "실패상세": failed_mst,
        "버전들": fetched,
    }
    out_path = DATA_DIR / f"{code}_history.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [SAVE] {out_path.name} ({out_path.stat().st_size / 1024:.0f}KB)", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", nargs="*", default=list(LAWS.keys()))
    parser.add_argument("--only-latest", action="store_true",
                        help="현행 1건만 — 메타 확인용 빠른 수집")
    parser.add_argument("--metadata-only", action="store_true",
                        help="법령MST 목록만")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"=== Phase 3 신규 법령 수집 ({len(args.codes)}개) ===", flush=True)
    print(f"대상: {', '.join(args.codes)}", flush=True)
    print(f"출력 경로(절대): {DATA_DIR}", flush=True)

    summary = {}
    for code in args.codes:
        if code not in LAWS:
            print(f"  [SKIP] unknown code: {code}", flush=True)
            continue
        name = LAWS[code]
        if args.metadata_only:
            history = search_history(name)
            (DATA_DIR / f"{code}_meta.json").write_text(
                json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
            summary[code] = {"name": name, "versions": len(history),
                             "earliest": history[0].get("시행일자") if history else None,
                             "latest": history[-1].get("시행일자") if history else None}
        else:
            r = collect_one(code, name, only_latest=args.only_latest)
            if r:
                summary[code] = {"name": name,
                                 "requested": r["버전수_요청"],
                                 "success": r["버전수_성공"],
                                 "failed": len(r["실패상세"])}
            else:
                summary[code] = {"name": name, "ERROR": "no history found"}

    (DATA_DIR / "_collection_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[SUMMARY]\n{json.dumps(summary, ensure_ascii=False, indent=2)}", flush=True)


if __name__ == "__main__":
    main()
