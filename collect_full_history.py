"""
도로교통법 전체 개정 연혁 수집기
================================
도로교통법, 도로교통법 시행령, 도로교통법 시행규칙 3개 법령의
전체 개정 연혁을 수집하고, 법률↔시행령↔시행규칙 간 연쇄 개정을 매칭합니다.

사용법:
    python collect_full_history.py

출력:
    - data/road_traffic_full_history.json
    - docs/road_traffic_full_history_summary.md
"""

import requests
import xml.etree.ElementTree as ET
import json
import os
import re
import time
from datetime import datetime

# === 설정 ===
API_KEY = "evergreen_edu"
DETAIL_URL = "http://www.law.go.kr/DRF/lawService.do"
HISTORY_LIST_URL = "https://www.law.go.kr/LSW/lsHstListR.do"
REQUEST_DELAY = 0.6  # API 요청 간격 (초)
SAVE_INTERVAL = 10   # 중간 저장 간격 (건)

# 수집 대상 법령 — 법령ID는 법제처 고유 식별자
LAW_GROUP = [
    {"유형": "법률",     "법령명": "도로교통법",         "법령ID": "001638"},
    {"유형": "시행령",   "법령명": "도로교통법 시행령",   "법령ID": "003395"},
    {"유형": "시행규칙", "법령명": "도로교통법 시행규칙", "법령ID": "007079"},
]

# 스크립트 위치 기준 경로
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
DOCS_DIR = os.path.join(SCRIPT_DIR, "docs")


def safe_text(element, tag: str) -> str:
    """XML 요소에서 안전하게 텍스트 추출"""
    el = element.find(tag)
    if el is not None and el.text:
        return el.text.strip()
    return ""


def format_date(date_str: str) -> str:
    """'20180327' → '2018.03.27' 형식으로 변환"""
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}.{date_str[4:6]}.{date_str[6:]}"
    return date_str


def parse_date(date_str: str):
    """'20180327' → datetime 객체. 파싱 실패 시 None 반환"""
    try:
        return datetime.strptime(date_str[:8], "%Y%m%d")
    except (ValueError, TypeError):
        return None


def save_checkpoint(result: dict, path: str):
    """중간 저장 — 수집 중 오류 발생 시 복구용"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def load_checkpoint(path: str) -> dict | None:
    """중간 저장 파일이 있으면 로드"""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def fetch_history_list(law_id: str, law_name: str) -> list[dict]:
    """
    법제처 웹사이트에서 전체 연혁 목록(MST, 공포일자, 공포번호, 시행일자, 제개정구분)을 추출합니다.
    lawSearch API는 현행 법령만 반환하므로, lsHstListR.do 페이지를 파싱합니다.
    """
    print(f"\n📋 [{law_name}] 연혁 목록 검색 중...")
    params = {"lsId": law_id}
    try:
        resp = requests.get(
            HISTORY_LIST_URL, params=params, timeout=30,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ❌ 연혁 목록 조회 실패: {e}")
        return []

    # onclick 패턴에서 연혁 정보 추출
    # lsViewLsHst2('MST', '공포일자', '공포번호', '시행일자', 'Y/N', '0', '제개정구분')
    pattern = r"lsViewLsHst2\('(\d+)',\s*'(\d+)',\s*'(\d+)',\s*'(\d+)',\s*'[^']*',\s*'[^']*'\s*,\s*'([^']*)'\)"
    matches = re.findall(pattern, resp.text)

    # 중복 제거 (같은 공포번호의 시행일이 다른 버전이 있을 수 있음 — MST+시행일자 기준)
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

    print(f"  ✅ {len(items)}건 발견")
    # 공포일자 기준 내림차순 (최신 → 과거)
    return sorted(items, key=lambda x: x["공포일자"], reverse=True)


def fetch_law_detail(mst: str) -> dict | None:
    """
    법령 본문을 가져와서 제개정이유, 부칙, 개정문을 추출합니다.
    """
    params = {
        "OC": API_KEY,
        "target": "law",
        "type": "XML",
        "MST": mst,
    }
    try:
        resp = requests.get(DETAIL_URL, params=params, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    ❌ 본문 조회 실패 (MST={mst}): {e}")
        return None

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        print(f"    ❌ XML 파싱 실패 (MST={mst})")
        return None

    # 기본정보
    basic = root.find(".//기본정보")
    if basic is None:
        basic = root
    info = {
        "법령명": safe_text(basic, "법령명_한글") or safe_text(basic, "법령명한글"),
        "법령ID": safe_text(basic, "법령ID"),
        "공포일자": safe_text(basic, "공포일자"),
        "공포번호": safe_text(basic, "공포번호"),
        "시행일자": safe_text(basic, "시행일자"),
        "제개정구분": safe_text(basic, "제개정구분"),
        "소관부처": safe_text(basic, "소관부처"),
    }

    # 제개정이유
    reason = safe_text(root, "제개정이유내용")
    if not reason:
        reason_el = root.find(".//제개정이유")
        if reason_el is not None:
            reason = safe_text(reason_el, "제개정이유내용") or (reason_el.text or "").strip()
    info["제개정이유내용"] = reason

    # 부칙 — 시행일 관련 내용 추출
    addenda = []
    for bk in root.findall(".//부칙단위"):
        content = safe_text(bk, "부칙내용")
        if "시행일" in content or "시행한다" in content or "경과조치" in content:
            addenda.append({
                "부칙공포일자": safe_text(bk, "부칙공포일자"),
                "부칙공포번호": safe_text(bk, "부칙공포번호"),
                "부칙내용": content,
            })
    info["부칙"] = addenda

    # 개정문 — 앞 500자만
    amend_text = safe_text(root, "개정문내용")
    if not amend_text:
        amend_el = root.find(".//개정문")
        if amend_el is not None:
            amend_text = safe_text(amend_el, "개정문내용") or (amend_el.text or "").strip()
    info["개정문내용요약"] = amend_text[:500] if amend_text else ""

    return info


def _build_cache_index(prev_result: dict) -> dict:
    """
    기존 결과에서 (법령유형 → {(공포일자, 공포번호): entry}) 인덱스 생성.
    API는 같은 MST의 여러 시행일자 항목에 대해 동일 detail(대표 시행일자 1개)을 반환하므로
    (공포일자, 공포번호) 2-튜플로 캐시 매핑하면 history_list의 다중 시행일 항목이 모두 매칭된다.
    """
    cache = {}
    for ld in prev_result.get("법령목록", []):
        t = ld.get("법령유형")
        if not t:
            continue
        type_cache = {}
        for e in ld.get("연혁", []):
            key = (e.get("공포일자", ""), e.get("공포번호", ""))
            if key not in type_cache:
                type_cache[key] = e
        cache[t] = type_cache
    return cache


def collect_all_history() -> dict:
    """
    3개 법령의 전체 개정 연혁을 수집합니다.
    기존 결과 파일을 캐시로 사용 — 신규 공포건만 API 본문 조회 (증분 수집).
    GitHub Actions 매주 자동 갱신 시 보통 0~3건만 처리하여 1분 이내 완료됩니다.
    """
    output_path = os.path.join(DATA_DIR, "road_traffic_full_history.json")
    checkpoint_path = os.path.join(DATA_DIR, "road_traffic_full_history_checkpoint.json")

    print("=" * 55)
    print("  도로교통법 전체 개정 연혁 수집기")
    print("  대상: 도로교통법 / 시행령 / 시행규칙")
    print("=" * 55)

    # 1) 기존 최종 결과 로드 → 캐시 인덱스 구축 (증분 수집의 기준)
    cache = {}
    if os.path.exists(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                prev_result = json.load(f)
            cache = _build_cache_index(prev_result)
            total_cached = sum(len(v) for v in cache.values())
            print(f"\n📚 기존 결과 캐시 로드: {total_cached}건 (신규 공포건만 API 조회 예정)")
        except Exception as e:
            print(f"\n⚠️ 기존 결과 로드 실패 — 전체 재수집합니다: {e}")
            cache = {}
    else:
        print(f"\n📭 기존 결과 없음 — 전체 수집을 시작합니다 (첫 실행).")

    result = {
        "생성일시": datetime.now().isoformat(),
        "설명": "도로교통법, 시행령, 시행규칙 3개 법령의 전체 개정 연혁",
        "법령목록": [],
    }

    for law_info in LAW_GROUP:
        law_type = law_info["유형"]
        law_name = law_info["법령명"]
        law_id = law_info["법령ID"]

        print(f"\n{'=' * 55}")
        print(f"📖 {law_type}: {law_name}")
        print(f"{'=' * 55}")

        # 법제처 웹에서 전체 연혁 목록 가져오기 (가벼움)
        history_list = fetch_history_list(law_id, law_name)
        if not history_list:
            print(f"  ⚠️ {law_name}: 연혁 없음, 건너뜁니다.")
            continue

        type_cache = cache.get(law_type, {})
        law_data = {
            "법령유형": law_type,
            "법령명": law_name,
            "전체연혁수": len(history_list),
            "연혁": [],
        }

        # 신규 수집 시 같은 MST 반복 호출 방지용 캐시
        detail_by_mst = {}

        new_count = 0
        cached_count = 0
        for i, ver in enumerate(history_list):
            cache_key = (ver["공포일자"], ver["공포번호"])
            if cache_key in type_cache:
                # 캐시 히트 — 기존 entry 재사용 (API 호출 생략)
                law_data["연혁"].append(type_cache[cache_key])
                cached_count += 1
                continue

            # 캐시 미스 — 신규 공포건이므로 본문 조회
            mst = ver["MST"]
            pub_date = ver["공포일자"]
            rev_type = ver["제개정구분"]

            # 같은 MST 재호출 방지 (대표 detail 1번만 받음)
            if mst in detail_by_mst:
                detail = detail_by_mst[mst]
                print(f"  📄 [신규 {new_count+1}] "
                      f"{format_date(pub_date)} ({rev_type}) MST={mst} (캐시 detail 재사용)")
            else:
                print(f"  📄 [신규 {new_count+1}] "
                      f"{format_date(pub_date)} ({rev_type}) MST={mst} 조회 중...")
                time.sleep(REQUEST_DELAY)
                detail = fetch_law_detail(mst)
                detail_by_mst[mst] = detail
            if not detail:
                # 본문 조회 실패 시 연혁 목록의 기본 정보만 저장
                law_data["연혁"].append({
                    "법령명": law_name,
                    "공포일자": pub_date,
                    "공포번호": ver["공포번호"],
                    "시행일자": ver["시행일자"],
                    "제개정구분": rev_type,
                    "제개정이유내용": "",
                    "부칙": [],
                    "개정문내용요약": "",
                    "조회실패": True,
                })
            else:
                law_data["연혁"].append({
                    "법령명": detail.get("법령명", law_name),
                    "공포일자": detail.get("공포일자", pub_date),
                    "공포번호": detail.get("공포번호", ver["공포번호"]),
                    "시행일자": detail.get("시행일자", ver["시행일자"]),
                    "제개정구분": detail.get("제개정구분", rev_type),
                    "제개정이유내용": detail.get("제개정이유내용", ""),
                    "부칙": detail.get("부칙", []),
                    "개정문내용요약": detail.get("개정문내용요약", ""),
                })
            new_count += 1

            # 신규 N건마다 중간 저장 (대량 신규 수집 중 중단 대비)
            if new_count % SAVE_INTERVAL == 0:
                temp_result = {
                    "생성일시": result["생성일시"],
                    "설명": result["설명"],
                    "법령목록": result["법령목록"] + [law_data],
                }
                save_checkpoint(temp_result, checkpoint_path)
                print(f"    💾 중간 저장 (신규 {new_count}건)")

        # 공포일자 내림차순 정렬 (캐시+신규 혼합 → 일관된 순서 보장)
        law_data["연혁"].sort(key=lambda x: x.get("공포일자", ""), reverse=True)

        if new_count == 0:
            print(f"\n  ✅ {law_name}: {len(history_list)}건 (모두 캐시, 신규 0건)")
        else:
            print(f"\n  ✅ {law_name}: {len(history_list)}건 (캐시 {cached_count} + 신규 {new_count})")
        result["법령목록"].append(law_data)

    # 정상 완료 시 체크포인트 삭제
    if os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)

    return result


def match_chain_amendments(result: dict):
    """
    법률↔시행령↔시행규칙 간 연쇄 개정을 매칭합니다.
    공포일 기준 전후 3개월(90일) 이내이면 연관으로 표시합니다.
    """
    print(f"\n🔗 법률↔시행령↔시행규칙 연쇄 개정 매칭 중...")
    THRESHOLD_DAYS = 90

    # 법령별 연혁을 {법령유형: [(공포일datetime, entry), ...]} 형태로 정리
    law_map = {}
    for law_data in result.get("법령목록", []):
        law_type = law_data["법령유형"]
        entries = []
        for entry in law_data["연혁"]:
            dt = parse_date(entry.get("공포일자", ""))
            if dt:
                entries.append((dt, entry))
        law_map[law_type] = entries

    match_count = 0

    for law_data in result.get("법령목록", []):
        my_type = law_data["법령유형"]
        for entry in law_data["연혁"]:
            my_dt = parse_date(entry.get("공포일자", ""))
            if not my_dt:
                continue

            linked = []
            for other_type, other_entries in law_map.items():
                if other_type == my_type:
                    continue
                for other_dt, other_entry in other_entries:
                    diff = abs((my_dt - other_dt).days)
                    if diff <= THRESHOLD_DAYS:
                        linked.append({
                            "법령유형": other_type,
                            "법령명": other_entry.get("법령명", ""),
                            "공포일자": other_entry.get("공포일자", ""),
                            "제개정구분": other_entry.get("제개정구분", ""),
                            "일자차이": diff,
                        })

            if linked:
                linked.sort(key=lambda x: x["일자차이"])
                entry["연쇄개정"] = linked
                match_count += 1

    print(f"  ✅ {match_count}건의 연쇄 개정 매칭 완료")


def save_json(result: dict, output_path: str):
    """결과를 JSON 파일로 저장"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"💾 JSON 저장 완료: {output_path}")


def save_markdown(result: dict, output_path: str):
    """결과를 마크다운 요약 파일로 저장"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    lines = []

    lines.append("# 도로교통법 전체 개정 연혁\n")
    lines.append(f"생성일시: {result.get('생성일시', '')}\n")

    for law_data in result.get("법령목록", []):
        law_type = law_data["법령유형"]
        law_name = law_data["법령명"]
        total = law_data["전체연혁수"]

        lines.append(f"\n## {law_type}: {law_name}\n")
        lines.append(f"전체 연혁 수: **{total}건**\n")

        # 요약 표
        lines.append("| 공포일 | 시행일 | 제개정구분 | 개정이유(앞 100자) |")
        lines.append("|--------|--------|-----------|-------------------|")

        for entry in law_data.get("연혁", []):
            pub = format_date(entry.get("공포일자", ""))
            eff = format_date(entry.get("시행일자", ""))
            rev = entry.get("제개정구분", "")
            reason = entry.get("제개정이유내용", "")
            reason_short = reason.replace("\n", " ").replace("\r", "").replace("|", "｜")[:100]
            if len(reason) > 100:
                reason_short += "..."
            lines.append(f"| {pub} | {eff} | {rev} | {reason_short} |")

        # 상세 서술
        lines.append(f"\n### 상세 내용\n")

        for entry in law_data.get("연혁", []):
            pub = format_date(entry.get("공포일자", ""))
            rev = entry.get("제개정구분", "")
            lines.append(f"#### {pub} ({rev})\n")

            lines.append(f"- **공포일**: {pub}")
            lines.append(f"- **공포번호**: 제{entry.get('공포번호', '')}호")
            lines.append(f"- **시행일**: {format_date(entry.get('시행일자', ''))}")
            lines.append(f"- **제개정구분**: {rev}")

            # 연쇄 개정 표시
            chain = entry.get("연쇄개정", [])
            if chain:
                chain_items = []
                for c in chain:
                    c_pub = format_date(c.get("공포일자", ""))
                    chain_items.append(
                        f"{c['법령유형']}({c_pub}, {c['제개정구분']}, "
                        f"차이 {c['일자차이']}일)"
                    )
                lines.append(f"- **연쇄 개정**: {', '.join(chain_items)}")

            # 제개정이유
            reason = entry.get("제개정이유내용", "")
            if reason:
                lines.append(f"\n**제개정이유:**\n")
                lines.append(f"{reason}\n")

            # 부칙(시행일 관련)
            addenda = entry.get("부칙", [])
            if addenda:
                lines.append("**부칙(시행일 관련):**\n")
                for bk in addenda:
                    bk_pub = format_date(bk.get("부칙공포일자", ""))
                    lines.append(f"- 공포일: {bk_pub}")
                    lines.append(f"```\n{bk.get('부칙내용', '')[:1000]}\n```\n")

            # 개정문 요약
            amend = entry.get("개정문내용요약", "")
            if amend:
                lines.append(f"**개정문(앞 500자):**\n")
                lines.append(f"```\n{amend}\n```\n")

            lines.append("---\n")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"📝 마크다운 저장 완료: {output_path}")


def main():
    json_path = os.path.join(DATA_DIR, "road_traffic_full_history.json")
    md_path = os.path.join(DOCS_DIR, "road_traffic_full_history_summary.md")

    # 전체 연혁 수집 (10건마다 중간 저장)
    result = collect_all_history()

    # 연쇄 개정 매칭
    match_chain_amendments(result)

    # 최종 저장
    save_json(result, json_path)
    save_markdown(result, md_path)

    # 요약 통계
    print(f"\n{'=' * 55}")
    print("📊 수집 결과 요약")
    print(f"{'=' * 55}")
    total_all = 0
    for law_data in result.get("법령목록", []):
        cnt = len(law_data.get("연혁", []))
        total_all += cnt
        chain_cnt = sum(1 for e in law_data["연혁"] if e.get("연쇄개정"))
        print(f"  📖 {law_data['법령유형']}: {cnt}건 (연쇄 개정 {chain_cnt}건)")

    print(f"  -------------------------")
    print(f"  총 {total_all}건 수집")
    print(f"\n✅ 완료!")
    print(f"  - JSON: {json_path}")
    print(f"  - 마크다운: {md_path}")


if __name__ == "__main__":
    main()
