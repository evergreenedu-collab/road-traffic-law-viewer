"""
교특법·뺑소니·민식이법 법원 판례 추가 수집 시제품 (Stage 6 기초)
================================================================
target=prec (법원판례) 사용 — 형사 사건은 decc(행정심판)에 없음 (밤새 발견).
기존 `도로교통법-한눈에-tutor/tutor/data/court_cases_data.json`(758건, 대법원)과
**사건번호 중복 제외**하고 교통사고 관련 신규 판례 수집.

Codex 검증 반영:
  - 응답 필드: 판례일련번호(not 행정심판재결례일련번호), 사건명, 사건번호,
    선고일자, 법원명, 사건종류명
  - XML 파서 singleton/list 둘 다 견고
  - 대법원만 필터(curt=대법원) 적용 가능
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
DATA_DIR.mkdir(exist_ok=True)

# 기존 대법원 판례 (사용자가 이미 보유한 758건)
EXISTING_COURT = Path(
    r"c:\Users\user\projects\도로교통법-한눈에-tutor\tutor\data\court_cases_data.json"
)

OC = "evergreen_edu"
SEARCH_URL = "http://www.law.go.kr/DRF/lawSearch.do"
SERVICE_URL = "http://www.law.go.kr/DRF/lawService.do"
REQUEST_DELAY = 0.3

QUERIES = [
    "교통사고처리특례법",          # 교특법 직접
    "도주차량",                    # 특가법 제5조의3 (뺑소니)
    "도주치사",                    # 특가법 5조의3 변형
    "도주치상",                    # 특가법 5조의3 변형
    "위험운전치사상",              # 특가법 제5조의11 (음주·약물)
    "위험운전치사",                # 5조의11 변형
    "위험운전치상",                # 5조의11 변형
    "어린이 보호구역",             # 특가법 제5조의13 (구 민식이법) — 띄어쓰기 포함
    "어린이보호구역치사상",        # 5조의13 변형
    "어린이보호구역치사",          # 5조의13 변형
    "스쿨존",                      # 어린이보호구역 별칭
    "특정범죄가중처벌",            # 광범위 검색 — 사건명 필터로 교통만 추림
]

# 사건명에 이 키워드 중 하나라도 포함돼야 교통 관련으로 채택
# (특가법 980건 중 비교통(마약·뇌물 등) 제외용)
TRAFFIC_TITLE_KEYWORDS = [
    "도로교통", "교통사고처리", "도주차량", "도주치",
    "위험운전", "어린이보호", "어린이 보호",
    "자동차", "운전자", "음주", "무면허", "운행 중",
    "특가법(어린", "특가법(도주", "특가법(위험",
]


def is_traffic_case(case_name):
    """사건명이 교통 관련 키워드를 포함하는지."""
    if not case_name:
        return False
    return any(k in case_name for k in TRAFFIC_TITLE_KEYWORDS)


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
    raise RuntimeError(f"API 호출 실패: {last}")


def load_existing_case_nos():
    """기존 court_cases_data.json의 case_no 집합."""
    if not EXISTING_COURT.exists():
        print(f"  [WARN] {EXISTING_COURT} 없음 — 중복 제외 비활성화", flush=True)
        return set()
    data = json.loads(EXISTING_COURT.read_text(encoding="utf-8"))
    items = data.get("데이터", data) if isinstance(data, dict) else data
    case_nos = set()
    if isinstance(items, dict):
        for v in items.values():
            if isinstance(v, dict):
                cno = v.get("case_no") or v.get("사건번호")
                if cno:
                    case_nos.add(str(cno).strip())
    elif isinstance(items, list):
        for v in items:
            if isinstance(v, dict):
                cno = v.get("case_no") or v.get("사건번호")
                if cno:
                    case_nos.add(str(cno).strip())
    print(f"  [LOAD] existing case_nos: {len(case_nos)}", flush=True)
    return case_nos


def _findtext(el, *tags):
    """여러 태그 후보 중 첫 매칭 — 응답 필드명 변동 대비."""
    for t in tags:
        v = el.findtext(t)
        if v:
            return v.strip()
    return ""


def search_prec(query, existing_nos, max_pages=40, traffic_filter=False):
    """법원판례 목록 — 사건번호 중복 제외 + (옵션) 사건명 교통 필터."""
    print(f"\n[QUERY] {query} (filter={'ON' if traffic_filter else 'off'})", flush=True)
    items = []
    page = 1
    total = 0
    dup = 0
    non_traffic = 0
    while page <= max_pages:
        xml = fetch(SEARCH_URL, {"OC": OC, "target": "prec", "type": "XML",
                                 "query": query, "display": 100, "page": page})
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            print(f"  [ERR] XML parse failed page {page}", flush=True)
            break
        total = int(root.findtext("totalCnt") or 0)
        rows = root.findall("prec")
        if not rows:
            break
        for d in rows:
            cno = _findtext(d, "사건번호")
            sid = _findtext(d, "판례일련번호")
            name = _findtext(d, "사건명")
            date = _findtext(d, "선고일자")
            court = _findtext(d, "법원명")
            kind = _findtext(d, "사건종류명")
            if not cno or not sid:
                continue
            if cno in existing_nos:
                dup += 1
                continue
            if traffic_filter and not is_traffic_case(name):
                non_traffic += 1
                continue
            items.append({
                "사건번호": cno,
                "사건명": name,
                "선고일자": date,
                "법원명": court,
                "사건종류명": kind,
                "판례일련번호": sid,
                "검색쿼리": query,
            })
        if page * 100 >= total:
            break
        page += 1
        time.sleep(REQUEST_DELAY)
    extra = f", non_traffic_excluded={non_traffic}" if traffic_filter else ""
    print(f"  [OK] new={len(items)}, dup={dup}, total_api={total}{extra}", flush=True)
    return items, total, dup, non_traffic


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"=== Phase 3 추가 판례 수집 (target=prec) ===", flush=True)
    print(f"출력 경로(절대): {DATA_DIR}", flush=True)
    existing = load_existing_case_nos()
    summary = {"기존_사건번호수": len(existing), "쿼리별": {}}
    all_new = []
    for q in QUERIES:
        try:
            # 특가법 광범위 검색만 사건명 필터 적용
            traffic_filter = (q == "특정범죄가중처벌")
            new, total, dup, nt = search_prec(q, existing, traffic_filter=traffic_filter)
            summary["쿼리별"][q] = {"신규": len(new), "중복": dup,
                                    "API총건수": total, "교통외제외": nt}
            all_new.extend(new)
        except Exception as e:
            print(f"  [ERR] {type(e).__name__}: {e}", flush=True)
            summary["쿼리별"][q] = {"ERROR": str(e)}

    # 사건번호 기준 dedup (여러 쿼리 매칭)
    seen = set()
    deduped = []
    for c in all_new:
        if c["사건번호"] in seen:
            continue
        seen.add(c["사건번호"])
        deduped.append(c)

    # 사건종류명 분포 (형사·민사 등 확인)
    from collections import Counter
    kind_dist = Counter(c.get("사건종류명", "") for c in deduped)
    summary["전체_신규_사건수"] = len(deduped)
    summary["사건종류명_분포"] = dict(kind_dist.most_common())
    # 법원별 분포
    court_dist = Counter(c.get("법원명", "") for c in deduped)
    summary["법원별_분포"] = dict(court_dist.most_common())

    print(f"\n[SUMMARY] new candidates: {len(deduped)}", flush=True)
    print(f"  사건종류명: {dict(kind_dist.most_common(5))}", flush=True)
    print(f"  법원별: {dict(court_dist.most_common(5))}", flush=True)

    (DATA_DIR / "extra_cases_candidates.json").write_text(
        json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA_DIR / "_extra_cases_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SAVE] extra_cases_candidates.json + _extra_cases_summary.json", flush=True)


if __name__ == "__main__":
    main()
