"""
도로교통법 3단 비교 매핑 구축 스크립트
======================================
법률 ↔ 시행령 ↔ 시행규칙 간 조·항 단위 위임 근거를 자동 추출하여
3단 매핑 데이터를 생성합니다.

사용법:
    python build_3tier_map.py

출력:
    - data/three_tier_map.json       (3단 매핑 데이터)
    - data/three_tier_articles.json  (전체 조문 원문 데이터)
"""

import argparse
import requests
import xml.etree.ElementTree as ET
import json
import os
import re
import time
from datetime import datetime
from collections import defaultdict

from api_utils import request_xml_with_retry

# === 설정 ===
API_KEY = "evergreen_edu"
DETAIL_URL = "http://www.law.go.kr/DRF/lawService.do"
REQUEST_DELAY = 0.6

# Phase 3 S1-A: 법령 그룹 dict-of-dict로 래핑. 향후 신규 그룹("tlspc" 등) 추가 시 키만 추가.
# 기존 LAWS 변수는 alias로 유지해 호출부 호환성 보장 (S1 범위 minimal).
LAW_GROUPS = {
    "road": {
        "법률":     {"법령명": "도로교통법",         "MST": "281875", "약칭": "법"},
        "시행령":   {"법령명": "도로교통법 시행령",   "MST": "269989", "약칭": "영"},
        "시행규칙": {"법령명": "도로교통법 시행규칙", "MST": "285317", "약칭": "규칙"},
    },
    # Phase 3 S3-1-b-2: 교통사고처리 특례법 — 현재 법률만 등록.
    # ⚠️ 교특법 시행령은 별도 존재(법령ID 002616). 향후 단계에서 MST 조회 후 추가.
    "tlspc": {
        "법률": {"법령명": "교통사고처리 특례법", "MST": "268077", "약칭": "법"},
        # TODO: 시행령 MST 조회 후 추가 — Codex 사후 검증 발견 (시행령 미수집은 우리 측 누락)
    },
}
LAWS = LAW_GROUPS["road"]   # S1-A: 호환성 alias (기존 사용처 그대로 + main()에서 --group으로 재바인딩)

# Phase 3 S3-1-b-1: 단일 법률 모드(시행령·시행규칙 없는 법령) 안전 폴백.
# 시행령/시행규칙 부재 시 빈 구조 반환 — 기존 3단 처리 코드가 KeyError 안 나도록.
EMPTY_LAW = {"기본정보": {}, "조문": {}, "공포일자": "", "법령ID": ""}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")


def safe_text(el, tag):
    """XML 요소에서 안전하게 텍스트 추출"""
    e = el.find(tag)
    if e is not None and e.text:
        return e.text.strip()
    return ""


def make_article_key(jo_num, jo_sub):
    """조문 고유 키 생성: '73' 또는 '73의2'"""
    key = str(jo_num)
    if jo_sub and jo_sub != "0":
        key += f"의{jo_sub}"
    return key


def make_full_key(jo_key, hang_num=None):
    """조·항 포함 전체 키: '제73조' 또는 '제73조 제2항'"""
    result = f"제{jo_key}조"
    if hang_num:
        result += f" 제{hang_num}항"
    return result


# 원문자 ↔ 아라비아 숫자 변환 테이블
_CIRCLE_NUMS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_CIRCLE_TO_ARABIC = {c: str(i + 1) for i, c in enumerate(_CIRCLE_NUMS)}
_ARABIC_TO_CIRCLE = {str(i + 1): c for i, c in enumerate(_CIRCLE_NUMS)}


def normalize_hang(hang_num):
    """항번호를 아라비아 숫자로 정규화: '①' → '1', '1' → '1'"""
    if not hang_num:
        return hang_num
    return _CIRCLE_TO_ARABIC.get(hang_num, hang_num)


def to_circle_hang(arabic_num):
    """아라비아 숫자를 원문자로: '1' → '①'"""
    if not arabic_num:
        return arabic_num
    return _ARABIC_TO_CIRCLE.get(str(arabic_num), str(arabic_num))


# =============================================================
#  1단계: 전체 조문 데이터 수집
# =============================================================
def fetch_all_articles():
    """3개 법령의 전체 조문 데이터를 수집합니다."""
    print("=" * 55)
    print("  1단계: 전체 조문 데이터 수집")
    print("=" * 55)

    all_data = {}

    for law_type, info in LAWS.items():
        law_name = info["법령명"]
        mst = info["MST"]
        print(f"\n📖 {law_type}: {law_name} (MST={mst})")

        params = {"OC": API_KEY, "target": "law", "type": "XML", "MST": mst}
        resp = request_xml_with_retry(DETAIL_URL, params, timeout=60)
        if resp is None:
            raise RuntimeError(f"본문 조회 최종 실패 ({law_type}, MST={mst})")
        root = ET.fromstring(resp.text)

        # 기본정보
        basic = root.find(".//기본정보")
        if basic is None:
            basic = root
        basic_info = {
            "법령명": safe_text(basic, "법령명_한글") or safe_text(basic, "법령명한글"),
            "공포일자": safe_text(basic, "공포일자"),
            "시행일자": safe_text(basic, "시행일자"),
        }

        # 조문 파싱 (장/절 구분 포함)
        articles = {}
        current_chapter = ""
        for jo in root.findall(".//조문단위"):
            jo_num = safe_text(jo, "조문번호")
            jo_sub = safe_text(jo, "조문가지번호")
            jo_type = safe_text(jo, "조문여부")
            jo_content = safe_text(jo, "조문내용")

            # 장/절 헤더 감지
            if jo_type == "전문" or (not safe_text(jo, "조문제목") and jo_content):
                import re as _re
                ch = _re.search(r"제(\d+)장\s*(.+)", jo_content)
                if ch:
                    current_chapter = f"제{ch.group(1)}장 {ch.group(2).strip()}"
                    # 개정 표시 제거
                    current_chapter = _re.sub(r"\s*<[^>]+>\s*$", "", current_chapter)
                    continue

            if not jo_num:
                continue

            jo_key = make_article_key(jo_num, jo_sub)
            jo_title = safe_text(jo, "조문제목")

            # 항 파싱
            paragraphs = []
            for hang in jo.findall(".//항"):
                h_num = safe_text(hang, "항번호")
                h_content = safe_text(hang, "항내용")

                # 호 파싱
                sub_items = []
                for ho in hang.findall(".//호"):
                    ho_num = safe_text(ho, "호번호")
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
                    if ho_content or mok_items:
                        sub_items.append({
                            "호번호": ho_num,
                            "호내용": ho_content,
                            "목": mok_items,
                        })

                paragraphs.append({
                    "항번호": h_num,
                    "항내용": h_content,
                    "호": sub_items,
                })

            articles[jo_key] = {
                "조문번호": jo_num,
                "조문가지번호": jo_sub,
                "조문키": jo_key,
                "조문제목": jo_title,
                "조문내용": jo_content,
                "장": current_chapter,
                "항": paragraphs,
            }

        all_data[law_type] = {
            "법령유형": law_type,
            "법령명": law_name,
            "약칭": info["약칭"],
            "기본정보": basic_info,
            "조문수": len(articles),
            "조문": articles,
        }
        print(f"  ✅ {len(articles)}개 조문 수집")
        time.sleep(REQUEST_DELAY)

    return all_data


# =============================================================
#  2단계: 위임 근거 참조 추출
# =============================================================

# 위임 근거 정규식 패턴들
# "법 제73조제2항", "법 제38조의2제1항제3호"
# "영 제38조제5항", "시행령 제38조의2제3항"
PATTERNS = {
    "법": re.compile(
        r'법\s*제(\d+)조(?:의(\d+))?'
        r'(?:\s*제(\d+)항)?'
        r'(?:\s*제(\d+)호)?'
    ),
    "영": re.compile(
        r'(?:영|시행령)\s*제(\d+)조(?:의(\d+))?'
        r'(?:\s*제(\d+)항)?'
        r'(?:\s*제(\d+)호)?'
    ),
}


def extract_references(text, pattern_key):
    """
    텍스트에서 위임 근거 참조를 추출합니다.
    "같은 조 제N항", "동조 제N항" 등 상대 참조도 처리합니다.
    반환: [{'조': '73', '조의': '', '항': '2', '호': ''}, ...]
    """
    if not text:
        return []
    pattern = PATTERNS[pattern_key]
    refs = []
    last_jo = None  # 가장 최근 참조된 조문번호 (상대 참조 해석용)
    last_jo_sub = ""

    for m in pattern.finditer(text):
        ref = {
            "조": m.group(1),
            "조의": m.group(2) or "",
            "항": m.group(3) or "",
            "호": m.group(4) or "",
        }
        last_jo = ref["조"]
        last_jo_sub = ref["조의"]
        refs.append(ref)

    # "같은 조 제N항", "동조 제N항" 상대 참조 처리
    if last_jo:
        relative_pattern = re.compile(
            r'(?:같은\s*조|동조)\s*제(\d+)항(?:\s*제(\d+)호)?'
        )
        for m in relative_pattern.finditer(text):
            ref = {
                "조": last_jo,
                "조의": last_jo_sub,
                "항": m.group(1),
                "호": m.group(2) or "",
            }
            # 이미 추출된 것과 중복 방지
            if not any(
                r["조"] == ref["조"] and r["조의"] == ref["조의"]
                and r["항"] == ref["항"]
                for r in refs
            ):
                refs.append(ref)

    return refs


def ref_to_article_key(ref):
    """참조 정보를 조문 키로 변환"""
    key = ref["조"]
    if ref["조의"]:
        key += f"의{ref['조의']}"
    return key


def build_reference_map(all_data):
    """
    시행령/시행규칙의 각 조·항에서 위임 근거를 추출하여
    매핑 테이블을 구축합니다.
    """
    print("\n" + "=" * 55)
    print("  2단계: 위임 근거 참조 추출")
    print("=" * 55)

    # 매핑 구조:
    # forward_map[시행령][시행령조키][시행령항] = [
    #   {"대상법령": "법률", "조키": "73", "항": "2", "호": "", "원문발췌": "..."}
    # ]
    forward_map = {
        "시행령": defaultdict(lambda: defaultdict(list)),
        "시행규칙": defaultdict(lambda: defaultdict(list)),
    }

    # --- 시행령 → 법률 참조 추출 (단일 법률 모드 대응: 시행령 없으면 EMPTY_LAW) ---
    decree_data = all_data.get("시행령", EMPTY_LAW)
    ref_count = 0
    for jo_key, article in decree_data["조문"].items():
        # 조문내용에서 추출
        if article["조문내용"]:
            refs = extract_references(article["조문내용"], "법")
            # 항이 있으면 항번호 추정 (항이 1개이고 항내용이 비어있으면 해당 항에 매핑)
            target_source = "조문"
            if article["항"] and len(article["항"]) == 1 and not article["항"][0]["항내용"]:
                target_source = article["항"][0]["항번호"] or "조문"
            elif article["항"]:
                # 항이 여러 개이고 항내용이 있으면 조문내용은 건너뜀
                refs = []
            for ref in refs:
                target_key = ref_to_article_key(ref)
                forward_map["시행령"][jo_key][target_source].append({
                    "대상법령": "법률",
                    "조키": target_key,
                    "항": ref["항"],
                    "호": ref["호"],
                })
                ref_count += 1

        # 각 항에서 추출 (항내용이 있는 경우만)
        for para in article["항"]:
            h_num = para["항번호"]
            if not para["항내용"]:
                continue
            refs = extract_references(para["항내용"], "법")
            for ref in refs:
                target_key = ref_to_article_key(ref)
                forward_map["시행령"][jo_key][h_num].append({
                    "대상법령": "법률",
                    "조키": target_key,
                    "항": ref["항"],
                    "호": ref["호"],
                })
                ref_count += 1

    print(f"\n📌 시행령 → 법률: {ref_count}건 참조 추출")

    # --- 시행규칙 → 법률/시행령 참조 추출 (단일 법률 모드 대응) ---
    rule_data = all_data.get("시행규칙", EMPTY_LAW)
    law_ref_count = 0
    decree_ref_count = 0

    for jo_key, article in rule_data["조문"].items():
        texts_to_check = []
        if article["조문내용"]:
            # 항이 1개이고 항내용이 비어있으면 조문내용을 해당 항에 매핑
            if article["항"] and len(article["항"]) == 1 and not article["항"][0]["항내용"]:
                target_id = article["항"][0]["항번호"] or "조문"
                texts_to_check.append((target_id, article["조문내용"]))
            elif not article["항"]:
                texts_to_check.append(("조문", article["조문내용"]))
            # 항이 여러 개이고 항내용이 있으면 조문내용은 건너뜀
        for para in article["항"]:
            if para["항내용"]:
                texts_to_check.append((para["항번호"], para["항내용"]))

        for source_id, text in texts_to_check:
            # 법률 참조
            for ref in extract_references(text, "법"):
                target_key = ref_to_article_key(ref)
                forward_map["시행규칙"][jo_key][source_id].append({
                    "대상법령": "법률",
                    "조키": target_key,
                    "항": ref["항"],
                    "호": ref["호"],
                })
                law_ref_count += 1

            # 시행령 참조
            for ref in extract_references(text, "영"):
                target_key = ref_to_article_key(ref)
                forward_map["시행규칙"][jo_key][source_id].append({
                    "대상법령": "시행령",
                    "조키": target_key,
                    "항": ref["항"],
                    "호": ref["호"],
                })
                decree_ref_count += 1

    print(f"📌 시행규칙 → 법률: {law_ref_count}건 참조 추출")
    print(f"📌 시행규칙 → 시행령: {decree_ref_count}건 참조 추출")

    return forward_map


# =============================================================
#  3단계: 역방향 매핑 구축 (법률 조·항 → 하위법령)
# =============================================================
def build_reverse_map(forward_map, all_data):
    """
    법률의 각 조·항에서 아래로 어떤 시행령/시행규칙이 연결되는지
    역방향 매핑을 구축합니다.
    """
    print("\n" + "=" * 55)
    print("  3단계: 역방향 매핑 구축 (법률 → 하위법령)")
    print("=" * 55)

    # reverse_map[법률조키][법률항] = [
    #   {"법령유형": "시행령", "조키": "38", "항": "2", "조문제목": "..."}
    # ]
    reverse_map = defaultdict(lambda: defaultdict(list))

    # 시행령 → 법률 역방향 (단일 법률 모드: 시행령 없으면 빈 dict)
    decree_articles = all_data.get("시행령", EMPTY_LAW).get("조문", {})
    for decree_jo, hang_map in forward_map["시행령"].items():
        decree_title = decree_articles.get(decree_jo, {}).get("조문제목", "")
        for source_hang, refs in hang_map.items():
            for ref in refs:
                if ref["대상법령"] == "법률":
                    law_jo = ref["조키"]
                    # 위임 근거의 항번호(아라비아)를 원문자로 변환하여 매칭
                    law_hang_arabic = ref["항"]
                    law_hang_circle = to_circle_hang(law_hang_arabic) if law_hang_arabic else ""
                    law_hang_key = law_hang_circle or "전체"

                    existing = reverse_map[law_jo][law_hang_key]
                    entry = {
                        "법령유형": "시행령",
                        "조키": decree_jo,
                        "항": source_hang,
                        "조문제목": decree_title,
                    }
                    if not any(
                        e["조키"] == entry["조키"] and e["항"] == entry["항"]
                        for e in existing
                    ):
                        existing.append(entry)

    # 시행규칙 → 법률 역방향 (단일 법률 모드: 시행규칙 없으면 빈 dict)
    rule_articles = all_data.get("시행규칙", EMPTY_LAW).get("조문", {})
    for rule_jo, hang_map in forward_map["시행규칙"].items():
        rule_title = rule_articles.get(rule_jo, {}).get("조문제목", "")
        for source_hang, refs in hang_map.items():
            for ref in refs:
                if ref["대상법령"] == "법률":
                    law_jo = ref["조키"]
                    law_hang_arabic = ref["항"]
                    law_hang_circle = to_circle_hang(law_hang_arabic) if law_hang_arabic else ""
                    law_hang_key = law_hang_circle or "전체"

                    existing = reverse_map[law_jo][law_hang_key]
                    entry = {
                        "법령유형": "시행규칙",
                        "조키": rule_jo,
                        "항": source_hang,
                        "조문제목": rule_title,
                    }
                    if not any(
                        e["조키"] == entry["조키"] and e["항"] == entry["항"]
                        for e in existing
                    ):
                        existing.append(entry)

    # 시행규칙 → 시행령 역방향 (시행령 경유 매핑)
    decree_reverse = defaultdict(lambda: defaultdict(list))
    for rule_jo, hang_map in forward_map["시행규칙"].items():
        rule_title = rule_articles.get(rule_jo, {}).get("조문제목", "")
        for source_hang, refs in hang_map.items():
            for ref in refs:
                if ref["대상법령"] == "시행령":
                    decree_jo = ref["조키"]
                    decree_hang_arabic = ref["항"]
                    decree_hang_circle = to_circle_hang(decree_hang_arabic) if decree_hang_arabic else ""
                    decree_hang_key = decree_hang_circle or "전체"

                    existing = decree_reverse[decree_jo][decree_hang_key]
                    entry = {
                        "법령유형": "시행규칙",
                        "조키": rule_jo,
                        "항": source_hang,
                        "조문제목": rule_title,
                    }
                    if not any(
                        e["조키"] == entry["조키"] and e["항"] == entry["항"]
                        for e in existing
                    ):
                        existing.append(entry)

    # 통계
    mapped_articles = len(reverse_map)
    total_links = sum(
        len(links)
        for hang_map in reverse_map.values()
        for links in hang_map.values()
    )
    print(f"  ✅ 법률 {mapped_articles}개 조문에 하위법령 {total_links}건 연결")

    decree_mapped = len(decree_reverse)
    decree_links = sum(
        len(links)
        for hang_map in decree_reverse.values()
        for links in hang_map.values()
    )
    print(f"  ✅ 시행령 {decree_mapped}개 조문에 시행규칙 {decree_links}건 연결")

    return reverse_map, decree_reverse


# =============================================================
#  3-2단계: 타법 참조 힌트 추출
# =============================================================
def extract_other_law_hints(all_data):
    """
    시행령/시행규칙이 법률 조문을 참조하면서 동시에 타법을 인용하는 경우,
    해당 타법명을 법률 조문에 힌트로 연결합니다.
    """
    print("\n" + "=" * 55)
    print("  3-2단계: 타법 참조 힌트 추출")
    print("=" * 55)

    SELF_LAWS = {"도로교통법", "도로교통법 시행령", "도로교통법 시행규칙"}
    law_ref_pattern = re.compile(
        r'법\s*제(\d+)조(?:의(\d+))?'
    )
    other_law_pattern = re.compile(r'\u300c([^\u300d]+)\u300d')

    hints = {}  # 법률조키 -> set(타법명)

    for law_type in ["시행령", "시행규칙"]:
        for jo_key, article in all_data.get(law_type, EMPTY_LAW).get("조문", {}).items():
            full = article.get("조문내용", "") or ""
            for p in article.get("항", []):
                full += " " + (p.get("항내용", "") or "")
                for ho in p.get("호", []):
                    full += " " + (ho.get("호내용", "") or "")

            law_refs = law_ref_pattern.findall(full)
            other_laws = other_law_pattern.findall(full)
            other_laws = [l for l in other_laws if l not in SELF_LAWS]

            if law_refs and other_laws:
                for ref in law_refs:
                    law_jo = ref[0] + (f"의{ref[1]}" if ref[1] else "")
                    if law_jo not in hints:
                        hints[law_jo] = set()
                    for ol in other_laws:
                        hints[law_jo].add(ol)

    # set → sorted list 변환
    hints = {k: sorted(v) for k, v in hints.items()}
    print(f"  ✅ {len(hints)}개 법률 조문에 타법 힌트 연결")

    return hints


# =============================================================
#  4단계: 최종 매핑 JSON 생성
# =============================================================
def build_final_map(all_data, reverse_map, decree_reverse, other_law_hints=None):
    """
    법률의 모든 조문에 대해 항별 하위법령 매핑을 포함한
    최종 3단 비교 데이터를 생성합니다.
    """
    print("\n" + "=" * 55)
    print("  4단계: 최종 3단 매핑 데이터 생성")
    print("=" * 55)

    law_articles = all_data["법률"]["조문"]
    decree_articles = all_data.get("시행령", EMPTY_LAW).get("조문", {})
    rule_articles = all_data.get("시행규칙", EMPTY_LAW).get("조문", {})

    law_name = all_data["법률"]["기본정보"].get("법령명", "법률")
    # 시행령 OR 시행규칙 둘 중 하나라도 조문 있으면 하위법령 존재 (Codex 권장)
    has_decree = bool(all_data.get("시행령", {}).get("조문"))
    has_rule = bool(all_data.get("시행규칙", {}).get("조문"))
    if has_decree and has_rule:
        desc = f"{law_name} 3단 비교 매핑 (법률 조·항 → 시행령 → 시행규칙)"
    elif has_decree or has_rule:
        desc = f"{law_name} 2단 매핑 (법률 + {'시행령' if has_decree else '시행규칙'})"
    else:
        desc = f"{law_name} 법률-only 출력 (시행령·시행규칙 미수집)"
    result = {
        "생성일시": datetime.now().isoformat(),
        "설명": desc,
        "기준법령": {
            "법률": all_data["법률"]["기본정보"],
            "시행령": all_data.get("시행령", EMPTY_LAW).get("기본정보", {}),
            "시행규칙": all_data.get("시행규칙", EMPTY_LAW).get("기본정보", {}),
        },
        "통계": {},
        "매핑": [],
    }

    mapped_count = 0
    unmapped_count = 0

    for jo_key in sorted(law_articles.keys(), key=lambda k: (
        int(re.match(r"(\d+)", k).group(1)),
        int((re.search(r"의(\d+)", k) or type("", (), {"group": lambda s, n: "0"})()).group(1))
    )):
        article = law_articles[jo_key]
        rev_map = reverse_map.get(jo_key, {})

        # 이 조문에 연결된 하위법령이 있는지
        has_links = len(rev_map) > 0

        entry = {
            "법률_조키": jo_key,
            "법률_조문제목": article["조문제목"],
            "법률_조문내용": article["조문내용"],
            "항별_매핑": [],
        }

        # 항이 있는 경우: 항별 매핑
        if article["항"]:
            for para in article["항"]:
                h_num = para["항번호"]

                # 이 항에 연결된 하위법령 (원문자 항번호로 매칭)
                # "전체" 키는 조문 전체에 관련된 것이므로 항별 매핑에 포함하지 않음
                linked_decree = rev_map.get(h_num, [])
                # 아라비아 숫자로도 시도 (혹시 키가 아라비아일 경우)
                h_arabic = normalize_hang(h_num)
                if h_arabic != h_num:
                    linked_decree = linked_decree + rev_map.get(h_arabic, [])
                # 중복 제거
                seen = set()
                unique_decree = []
                for ld in linked_decree:
                    k = (ld["법령유형"], ld["조키"], ld["항"])
                    if k not in seen:
                        seen.add(k)
                        unique_decree.append(ld)

                # 연결된 시행령/시행규칙의 실제 조문 내용 포함
                decree_links = []
                rule_links = []
                for link in unique_decree:
                    if link["법령유형"] == "시행령":
                        d_article = decree_articles.get(link["조키"], {})
                        d_info = {
                            "조키": link["조키"],
                            "항": link["항"],
                            "조문제목": d_article.get("조문제목", ""),
                            "조문내용": d_article.get("조문내용", ""),
                        }
                        # 해당 항의 내용만
                        if link["항"] and link["항"] != "조문":
                            for dp in d_article.get("항", []):
                                if dp["항번호"] == link["항"]:
                                    d_info["항내용"] = dp["항내용"]
                                    break

                        # 이 시행령 조문에 연결된 시행규칙 찾기
                        d_rev = decree_reverse.get(link["조키"], {})
                        link_hang = link["항"]
                        linked_rules = d_rev.get(link_hang, []) + d_rev.get("전체", [])
                        # 원문자/아라비아 양쪽 시도
                        link_hang_alt = normalize_hang(link_hang) if link_hang else ""
                        if link_hang_alt and link_hang_alt != link_hang:
                            linked_rules = linked_rules + d_rev.get(link_hang_alt, [])
                        seen_r = set()
                        for lr in linked_rules:
                            rk = (lr["조키"], lr["항"])
                            if rk not in seen_r:
                                seen_r.add(rk)
                                r_article = rule_articles.get(lr["조키"], {})
                                r_info = {
                                    "조키": lr["조키"],
                                    "항": lr["항"],
                                    "조문제목": r_article.get("조문제목", ""),
                                }
                                if lr["항"] and lr["항"] != "조문":
                                    for rp in r_article.get("항", []):
                                        if rp["항번호"] == lr["항"]:
                                            r_info["항내용"] = rp["항내용"]
                                            break
                                rule_links.append(r_info)

                        # 시행규칙 중복 제거
                        seen_rl = set()
                        unique_rule_links = []
                        for rl in rule_links:
                            rk = (rl["조키"], rl.get("항", ""))
                            if rk not in seen_rl:
                                seen_rl.add(rk)
                                unique_rule_links.append(rl)
                        d_info["시행규칙"] = unique_rule_links
                        decree_links.append(d_info)

                    elif link["법령유형"] == "시행규칙":
                        r_article = rule_articles.get(link["조키"], {})
                        r_info = {
                            "조키": link["조키"],
                            "항": link["항"],
                            "조문제목": r_article.get("조문제목", ""),
                        }
                        if link["항"] and link["항"] != "조문":
                            for rp in r_article.get("항", []):
                                if rp["항번호"] == link["항"]:
                                    r_info["항내용"] = rp["항내용"]
                                    break
                        # 시행령을 거치지 않고 직접 연결된 시행규칙
                        rule_links.append(r_info)

                # 직접 연결 시행규칙 중복 제거
                seen_rd = set()
                unique_rule_direct = []
                for rl in rule_links:
                    rk = (rl["조키"], rl.get("항", ""))
                    if rk not in seen_rd:
                        seen_rd.add(rk)
                        unique_rule_direct.append(rl)

                para_map = {
                    "항번호": h_num,
                    "항내용": para["항내용"],
                    "시행령": decree_links,
                    "시행규칙_직접": unique_rule_direct,
                }
                entry["항별_매핑"].append(para_map)

        if has_links:
            mapped_count += 1
        else:
            unmapped_count += 1

        # "전체" 키 (항 미지정) 매핑은 조문 단위로 별도 표시
        general_links = rev_map.get("전체", [])
        seen_gen = set()
        unique_general = []
        for gl in general_links:
            gk = (gl["법령유형"], gl["조키"], gl.get("항", ""))
            if gk not in seen_gen:
                seen_gen.add(gk)
                # 실제 조문 내용 추가
                if gl["법령유형"] == "시행령":
                    src = decree_articles.get(gl["조키"], {})
                elif gl["법령유형"] == "시행규칙":
                    src = rule_articles.get(gl["조키"], {})
                else:
                    src = {}
                gl_info = {
                    "법령유형": gl["법령유형"],
                    "조키": gl["조키"],
                    "항": gl.get("항", ""),
                    "조문제목": src.get("조문제목", gl.get("조문제목", "")),
                }
                unique_general.append(gl_info)
        entry["조문전체_매핑"] = unique_general

        entry["하위법령_존재"] = has_links or len(unique_general) > 0
        result["매핑"].append(entry)

    result["통계"] = {
        "법률_전체조문수": len(law_articles),
        "하위법령_연결조문수": mapped_count,
        "하위법령_미연결조문수": unmapped_count,
        "시행령_전체조문수": len(decree_articles),
        "시행규칙_전체조문수": len(rule_articles),
    }

    print(f"  ✅ 법률 {len(law_articles)}개 조문 중 {mapped_count}개에 하위법령 연결")
    print(f"     ({unmapped_count}개 조문은 하위법령 미연결)")

    return result


# =============================================================
#  저장
# =============================================================
def save_json(data, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"💾 저장 완료: {path} ({size_mb:.1f}MB)")


def main():
    # Phase 3 S3-1-b-2: --group 인자 추가. road는 기존 파일명 유지(viewer 호환),
    # 그 외(tlspc 등)는 _{group} suffix.
    parser = argparse.ArgumentParser(description="법령 3단(또는 단일) 매핑 빌더")
    parser.add_argument("--group", default="road", choices=list(LAW_GROUPS.keys()),
                        help="법령 그룹 코드 (기본 road = 도로교통법)")
    args = parser.parse_args()

    # 전역 LAWS 재바인딩 — fetch_all_articles 등이 module-level LAWS를 직접 참조
    global LAWS
    LAWS = LAW_GROUPS[args.group]
    group_label = LAWS["법률"]["법령명"]
    print(f"\n🏷️  법령 그룹: {args.group} ({group_label})")

    # road는 기존 파일명, 그 외는 suffix
    suffix = "" if args.group == "road" else f"_{args.group}"
    map_path = os.path.join(DATA_DIR, f"three_tier_map{suffix}.json")
    articles_path = os.path.join(DATA_DIR, f"three_tier_articles{suffix}.json")

    # 1단계: 전체 조문 수집
    all_data = fetch_all_articles()

    # 조문 원문 데이터 저장 (단일 법률 모드: 시행령·시행규칙 없으면 EMPTY_LAW)
    save_json({
        "생성일시": datetime.now().isoformat(),
        "법령그룹": args.group,
        "법령명": group_label,
        "법률": all_data["법률"],
        "시행령": all_data.get("시행령", EMPTY_LAW),
        "시행규칙": all_data.get("시행규칙", EMPTY_LAW),
    }, articles_path)

    # 2단계: 위임 근거 추출
    forward_map = build_reference_map(all_data)

    # 3단계: 역방향 매핑
    reverse_map, decree_reverse = build_reverse_map(forward_map, all_data)

    # 4단계: 최종 매핑 생성
    # 4단계: 최종 매핑
    final_map = build_final_map(all_data, reverse_map, decree_reverse)

    # 저장
    save_json(final_map, map_path)

    # 요약 출력
    stats = final_map["통계"]
    print(f"\n{'=' * 55}")
    print("📊 3단 매핑 결과 요약")
    print(f"{'=' * 55}")
    print(f"  법률 조문: {stats['법률_전체조문수']}개")
    print(f"  시행령 조문: {stats['시행령_전체조문수']}개")
    print(f"  시행규칙 조문: {stats['시행규칙_전체조문수']}개")
    print(f"  하위법령 연결: {stats['하위법령_연결조문수']}개 조문")
    print(f"  미연결: {stats['하위법령_미연결조문수']}개 조문")
    print(f"\n✅ 완료!")
    print(f"  - 매핑 데이터: {map_path}")
    print(f"  - 조문 원문: {articles_path}")


if __name__ == "__main__":
    main()
