"""
법원판례 본문 수집 — extra_cases_candidates.json의 판례일련번호 기반
====================================================================
lawService.do?target=prec&ID=<판례일련번호> 호출. 응답에서:
  사건명, 사건번호, 선고일자, 법원명, 사건종류명, 판시사항, 판결요지, 참조조문, 참조판례, 전문

기존 court_cases_data.json과 같은 형식(case_name/date/court/case_no/ruling)으로 변환,
다만 검색쿼리도 보존해서 추후 사건 출처 파악 가능.
"""

import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
assert ROOT_DIR.name == "overnight_phase3"
DATA_DIR = ROOT_DIR / "data"

OC = "evergreen_edu"
SERVICE_URL = "http://www.law.go.kr/DRF/lawService.do"
REQUEST_DELAY = 0.3

CAND_PATH = DATA_DIR / "extra_cases_candidates.json"
OUT_PATH = DATA_DIR / "extra_court_cases_data.json"


def fetch(url, params):
    q = urllib.parse.urlencode(params)
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url + "?" + q, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            last = e
            time.sleep(3 * (attempt + 1))
    return None


def _ft(root, *tags):
    for t in tags:
        for el in root.iter(t):
            if el.text:
                return el.text.strip()
    return ""


def fetch_detail(sid):
    xml = fetch(SERVICE_URL, {"OC": OC, "target": "prec", "type": "XML", "ID": sid})
    if not xml:
        return None
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    # 본문 합치기 — 판시사항 + 판결요지 + 전문 순
    psh = _ft(root, "판시사항")
    pgy = _ft(root, "판결요지")
    jeon = _ft(root, "판례내용", "전문")
    ruling_parts = []
    if psh:
        ruling_parts.append(f"[판시사항] {psh}")
    if pgy:
        ruling_parts.append(f"[판결요지] {pgy}")
    if jeon:
        ruling_parts.append(f"[전문] {jeon}")
    return {
        "case_name": _ft(root, "사건명"),
        "case_no": _ft(root, "사건번호"),
        "date": _ft(root, "선고일자"),
        "court": _ft(root, "법원명"),
        "case_kind": _ft(root, "사건종류명"),
        "ruling_type": _ft(root, "판결유형"),
        "ruling": "\n\n".join(ruling_parts),
        "참조조문": _ft(root, "참조조문"),
        "참조판례": _ft(root, "참조판례"),
        "판례일련번호": sid,
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if not CAND_PATH.exists():
        print(f"[ERR] not found: {CAND_PATH}", flush=True)
        sys.exit(1)
    cands = json.loads(CAND_PATH.read_text(encoding="utf-8"))
    print(f"=== 본문 수집: {len(cands)}건 ===", flush=True)
    fetched = {}
    fail = []
    for i, c in enumerate(cands, 1):
        sid = c.get("판례일련번호")
        cno = c.get("사건번호")
        if not sid:
            fail.append(("no_sid", c))
            continue
        d = fetch_detail(sid)
        if not d:
            fail.append(("fetch_failed", c))
            continue
        d["_검색쿼리"] = c.get("검색쿼리")
        fetched[cno or sid] = d
        if i % 20 == 0 or i == len(cands):
            print(f"  [{i}/{len(cands)}] ok={len(fetched)} fail={len(fail)}", flush=True)
        time.sleep(REQUEST_DELAY)

    out = {
        "생성일시": time.strftime("%Y-%m-%d %H:%M:%S"),
        "설명": "Phase 3 추가 형사 판례 (교특법·뺑소니·민식이법). 기존 court_cases_data.json과 별도.",
        "판례수": len(fetched),
        "실패수": len(fail),
        "데이터": fetched,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[SAVE] {OUT_PATH.name} ({OUT_PATH.stat().st_size / 1024 / 1024:.1f}MB)", flush=True)
    if fail:
        print(f"[FAIL] {len(fail)} cases — see _fetch_fail.json", flush=True)
        (DATA_DIR / "_fetch_fail.json").write_text(
            json.dumps([{"reason": r, "case": c} for r, c in fail],
                       ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
