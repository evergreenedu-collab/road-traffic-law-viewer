"""
캐스케이드 이벤트 구축 v3
============================
법률 ↔ 시행령 ↔ 시행규칙 매칭을 4단계 객관적 자료 기반으로 수행한다.
시간(공포 간격) 기반 매칭은 사용하지 않는다.
하위법령 공포는 상위법령 공포 다음날일 수도, 2년 뒤일 수도 있어 시간으로는 추정 불가.

매칭 단계 (단계마다 매칭된 건은 다음 단계에서 제외):
  Stage 1: 공포번호 매칭   — "법률 제19745호" / "대통령령 제35886호" 정확 매칭
  Stage 2: 공포일자 매칭   — "2023. 10. 24. 공포" 같은 패턴
  Stage 3: 시행일자 매칭   — "2024. 10. 25. 시행" 패턴 (동일 시행일 단일 후보일 때만)
  Stage 4: 텍스트 의미 매칭 — 변경조문 제목 + IDF 가중 키워드 (타법개정 제외, 임계값 높음)

시행규칙은 법률 또는 시행령 둘 중 직접부모에 매칭한다.
시행령에 매칭된 시행규칙은 그 시행령이 매칭된 법률 이벤트에 함께 표시한다.

사용법:
    python build_cascade_events.py
출력:
    data/cascade_events.json
"""

import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_addenda_effective import parse_addenda

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")

HISTORY_PATH = os.path.join(DATA_DIR, "article_history.json")
FULL_HISTORY_PATH = os.path.join(DATA_DIR, "road_traffic_full_history.json")
MAP_PATH = os.path.join(DATA_DIR, "three_tier_map.json")
TEXT_DIFF_PATH = os.path.join(DATA_DIR, "text_diff.json")
ATTACHED_TABLES_PATH = os.path.join(DATA_DIR, "attached_tables.json")
ATTACHED_TABLES_DIFF_PATH = os.path.join(DATA_DIR, "attached_tables_diff.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "cascade_events.json")

# 별표 제목에서 모법 조문 인용 추출
# 예: "(제91조제1항관련)", "[제18조제1항관련]", "(제46조제1항ㆍ제46조의2제1항 관련)"
TABLE_ARTICLE_PAT = re.compile(r"제(\d+(?:의\d+)?)조")
# 별표 본문에서 "법 제X조" / "도로교통법 제X조" 인용 추출 (법률 조문 직접 인용)
LAW_REF_IN_TABLE = re.compile(r"(?:도로교통)?법\s*제(\d+(?:의\d+)?)조")


# ─────────────────────────────────────────────────────────
# 텍스트 처리 유틸
# ─────────────────────────────────────────────────────────
HANGUL_CHUNK = re.compile(r"[가-힣]{2,}")  # 2글자 이상 한글 청크 (조사 포함)

# 한국어 조사/어미 — 청크 끝에서 떼어내어 어간 추출 (긴 것부터 시도)
SUFFIXES = sorted([
    # 어미 + 조사 결합
    "하도록", "하여서", "하여야", "하면서", "하느라", "되도록", "되어야",
    "되어서", "에서는", "에서도", "에서만", "에게서", "에게는", "으로써",
    "으로서", "으로는", "으로도", "으로만",
    # 단순 어미
    "하여", "하는", "하지", "하고", "하기", "하며", "한다", "되어", "되는",
    "되며", "되지", "된다", "있는", "있도", "있고", "되었", "있었",
    # 단순 조사
    "에서", "에게", "에는", "에도", "에만", "으로", "이라", "이며", "이고",
    "와는", "과는", "라고", "라는", "라면",
    "을", "를", "이", "가", "은", "는", "와", "과", "도", "만", "로",
    "에", "의", "며", "야", "나", "랑", "뿐",
], key=len, reverse=True)

# 정규화 후 의미 없는 일반어/법령 메타 (정규화 후 매칭에서 제외)
STOP_KEYWORDS = {
    "도로교통법", "도로교통법시행령", "도로교통법시행규칙",
    "법률", "시행령", "시행규칙", "대통령령", "행정안전부령", "총리령",
    "개정", "신설", "삭제", "일부개정", "전부개정", "타법개정", "공포",
    "주요내용", "주요골자", "개정이유", "법제처", "경찰청", "행정안전부",
    "현행", "다음", "다음과같", "다음과같이", "필요한", "사항", "내용",
    "관한", "대한", "위한", "위하여", "정하", "정하려", "있는경우",
    "있도록함", "도록함", "함으로", "한편", "운영상", "미비점", "개선보완",
    "이용", "사용", "방법", "기준", "대상", "범위", "절차", "조치",
    "지정", "고시", "통보", "신청", "제출", "발급", "취득", "확인",
    "각각", "또는", "기타", "현행제도", "이러", "이러한", "그러", "그러한",
    "이번", "종전", "앞으로", "한편으", "다만", "다음의", "이상의", "이하의",
    # 법률 관련 일반 동사형
    "개정되", "개정된", "개정될", "개정함", "개정함에",
}


def strip_suffix(w):
    """한국어 조사/어미를 청크 끝에서 반복 제거하여 어간 근사 추출"""
    changed = True
    while changed and len(w) >= 3:
        changed = False
        for s in SUFFIXES:
            if len(w) > len(s) + 1 and w.endswith(s):
                w = w[:-len(s)]
                changed = True
                break
    return w


def extract_keywords(text):
    """텍스트에서 한글 청크 추출 → 조사 제거 → stopword 제외 (3글자 이상만 유지)"""
    if not text:
        return set()
    out = set()
    for c in HANGUL_CHUNK.findall(text):
        c2 = strip_suffix(c)
        if len(c2) >= 3 and c2 not in STOP_KEYWORDS:
            out.add(c2)
    return out


# 숫자+한글 단위 키워드 (75세, 3년, 5만원, 1종 등) — 매우 변별적인 신호
NUM_HANGUL_PAT = re.compile(r"\d+(?:세|년|개월|달|일|시간|회|명|종|급|차|호|점|만원|원|미터|미만|이상|이하|초과)")


def extract_strong_title_keywords(titles):
    """변경조문 제목들에서 강한 신호 키워드 추출
    - 숫자+한글 단위(75세, 3년, 5만원 등) — 결정적
    - 4글자 이상 한글 청크 (어간 추출)
    """
    out = set()
    for t in titles:
        if not t:
            continue
        # 숫자+한글 단위
        out.update(NUM_HANGUL_PAT.findall(t))
        # 한글 청크
        for c in HANGUL_CHUNK.findall(t):
            c2 = strip_suffix(c)
            if len(c2) >= 4 and c2 not in STOP_KEYWORDS:
                out.add(c2)
    return out


def clean_title(t):
    """조문제목 양끝 괄호 제거"""
    t = (t or "").strip()
    if t.startswith("(") and t.endswith(")"):
        t = t[1:-1]
    return t


def parse_table_parent_articles(table_title):
    """별표 제목에서 모법 조문 키들 추출
    예: "운전면허 취소·정지처분 기준(제91조제1항관련)" → ["91"]
        "안전표지 ... (제8조제2항 및 제11조제1호관련)" → ["8", "11"]
        "교통안전교육 ... (제46조제1항ㆍ제46조의2제1항ㆍ제46조의3제2항 관련)" → ["46", "46의2", "46의3"]
    """
    return list(dict.fromkeys(TABLE_ARTICLE_PAT.findall(table_title or "")))


def norm_pubno(s):
    """공포번호 leading zero 정규화: '09845' → '9845'"""
    return str(s or "").lstrip("0") or "0"


# ─────────────────────────────────────────────────────────
# 패턴 (제개정이유에서 매칭 자료 추출)
# ─────────────────────────────────────────────────────────
LAW_NO_PAT = re.compile(r"(?:법률\s*제|법률제)(\d+)호")
DECREE_NO_PAT = re.compile(r"(?:대통령령\s*제|대통령령제)(\d+)호")
PUBDATE_PAT = re.compile(r"(\d{4})\s*[.년]\s*(\d{1,2})\s*[.월]\s*(\d{1,2})\s*[일.,]?\s*공포")
EFFDATE_PAT = re.compile(r"(\d{4})\s*[.년]\s*(\d{1,2})\s*[.월]\s*(\d{1,2})\s*[일.,]?\s*시행")
LAWNAME_PAT = re.compile(r"「도로교통법(?:\s*시행령)?」")  # "「도로교통법」" 또는 "「도로교통법 시행령」"


def parse_dates_in_text(text, pattern):
    """패턴에서 (year, month, day) 추출하여 YYYYMMDD 리스트 반환"""
    out = []
    for m in pattern.finditer(text):
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        out.append((f"{y}{mo}{d}", f"{y}.{int(mo)}.{int(d)}"))
    return out


# ─────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────
def main():
    print("📖 데이터 로딩...")
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        hist = json.load(f)
    with open(FULL_HISTORY_PATH, "r", encoding="utf-8") as f:
        full_hist = json.load(f)
    with open(MAP_PATH, "r", encoding="utf-8") as f:
        mapdata = json.load(f)
    if not os.path.exists(TEXT_DIFF_PATH):
        raise FileNotFoundError(
            f"{TEXT_DIFF_PATH} 없음. build_cascade_events.py는 text_diff.json에 의존합니다. "
            "먼저 build_text_diff.py를 실행하세요. (빌드 순서: text_diff → cascade_events)"
        )
    with open(TEXT_DIFF_PATH, "r", encoding="utf-8") as f:
        text_diff = json.load(f)
    attached_tables = {}
    if os.path.exists(ATTACHED_TABLES_PATH):
        with open(ATTACHED_TABLES_PATH, "r", encoding="utf-8") as f:
            attached_tables = json.load(f)
    # 별표 시점별 변경 이력 (선택적 — 없어도 동작)
    attached_diff = {}
    if os.path.exists(ATTACHED_TABLES_DIFF_PATH):
        with open(ATTACHED_TABLES_DIFF_PATH, "r", encoding="utf-8") as f:
            attached_diff = json.load(f)

    # 본문 실제 변경된 (조문키, 공포일자) 인덱스 + 변경유형/제목
    # API 메타데이터(조문변경여부)는 거짓 양성/음성이 모두 있어 신뢰 불가.
    # text_diff(인접 본문 비교 결과)를 단독 진실의 원천으로 사용.
    actual_change_index = {"법률": defaultdict(dict), "시행령": defaultdict(dict), "시행규칙": defaultdict(dict)}
    for law_type in ["법률", "시행령", "시행규칙"]:
        for jo_key, diffs in text_diff.get(law_type, {}).items():
            for d in diffs:
                # (공포일, 조문키) → {변경유형, 조문제목, 이후본문}
                actual_change_index[law_type][d["공포일자"]][jo_key] = {
                    "변경유형": d.get("변경유형", ""),
                    "조문제목": d.get("조문제목", ""),
                    "이후": d.get("이후", ""),
                }
    print(f"  text_diff 실제 변경 인덱스: 법률 {sum(len(v) for v in actual_change_index['법률'].values())}건, "
          f"시행령 {sum(len(v) for v in actual_change_index['시행령'].values())}건, "
          f"시행규칙 {sum(len(v) for v in actual_change_index['시행규칙'].values())}건")

    print("=" * 60)
    print("  캐스케이드 이벤트 구축 v3 (4단계 객관자료 매칭)")
    print("=" * 60)

    # ─────────────────────────────────────────────────────
    # 1. 공포번호 인덱스 (법률 + 시행령) — full_history 기반
    # ─────────────────────────────────────────────────────
    print("\n📌 1. 공포번호 인덱스 구축 (full_history)...")
    # 법령명 → 인덱스
    fullhist_by_name = {}
    for law in full_hist["법령목록"]:
        name = law.get("법령명_한글") or law.get("법령명") or ""
        fullhist_by_name[name] = law

    # 법률 공포번호 → 공포일자
    law_pubno_to_pubdate = {}  # 정규화 공포번호 → 공포일자
    for ver in fullhist_by_name.get("도로교통법", {}).get("연혁", []):
        pubno = norm_pubno(ver.get("공포번호", ""))
        if pubno and pubno not in law_pubno_to_pubdate:
            law_pubno_to_pubdate[pubno] = ver.get("공포일자", "")

    # 시행령 공포번호 → 공포일자
    decree_pubno_to_pubdate = {}
    for ver in fullhist_by_name.get("도로교통법 시행령", {}).get("연혁", []):
        pubno = norm_pubno(ver.get("공포번호", ""))
        if pubno and pubno not in decree_pubno_to_pubdate:
            decree_pubno_to_pubdate[pubno] = ver.get("공포일자", "")

    print(f"  법률 공포번호: {len(law_pubno_to_pubdate)}개")
    print(f"  시행령 공포번호: {len(decree_pubno_to_pubdate)}개")

    # ─────────────────────────────────────────────────────
    # 2. 변경조문 포함 버전 정리 (article_history 기반)
    # ─────────────────────────────────────────────────────
    print("\n📌 2. 변경조문 정리 (text_diff 단독 기준)...")
    versions = {"법률": {}, "시행령": {}, "시행규칙": {}}  # 공포일자 → 버전데이터
    rescued = {"법률": 0, "시행령": 0, "시행규칙": 0}  # API=N인데 본문 변경된 것 살린 카운트

    # fullhist 에서 (법령유형, 공포일자) → 부칙 리스트 매핑
    # article_history.json 에는 부칙이 없으므로 road_traffic_full_history.json 에서 따로 가져온다
    type_to_name = {
        "법률": "도로교통법",
        "시행령": "도로교통법 시행령",
        "시행규칙": "도로교통법 시행규칙",
    }
    addenda_by_pub = {"법률": {}, "시행령": {}, "시행규칙": {}}
    for lt, lname in type_to_name.items():
        for v in fullhist_by_name.get(lname, {}).get("연혁", []):
            pub = v.get("공포일자", "")
            if pub and pub not in addenda_by_pub[lt]:
                addenda_by_pub[lt][pub] = v.get("부칙", [])

    for law_type in ["법률", "시행령", "시행규칙"]:
        # text_diff에 등장하는 모든 공포일을 순회 (API 메타데이터 무시)
        # 이후 ver에서 본문/제목 정보 추출 시도, 없으면 text_diff 정보 사용
        ver_by_pub = {}
        for ver in hist["법령"].get(law_type, {}).get("버전", []):
            pub = ver.get("공포일자", "")
            if not pub:
                continue
            # 같은 공포일에 여러 버전이면 조문 데이터 더 풍부한 것 채택
            cur_arts = ver.get("조문", {})
            if pub not in ver_by_pub or len(cur_arts) > len(ver_by_pub[pub].get("조문", {})):
                ver_by_pub[pub] = ver

        # text_diff에 변경 기록이 있는 공포일만 처리
        for pub, jo_changes in actual_change_index[law_type].items():
            if pub not in ver_by_pub:
                continue
            ver = ver_by_pub[pub]
            changed = {}
            for jo_key, diff_meta in jo_changes.items():
                jo_data = ver.get("조문", {}).get(jo_key, {})
                # 본문/제목: jo_data 우선, 없으면 text_diff "이후"본문/제목
                title = clean_title(jo_data.get("조문제목", "") or diff_meta.get("조문제목", ""))
                content = jo_data.get("조문내용", "") or ""
                # API가 변경 안 됐다고 했지만 본문은 변경된 케이스 (거짓 음성 구제)
                api_changed = jo_data.get("조문변경여부") == "Y" or jo_data.get("조문제개정유형")
                if not api_changed:
                    rescued[law_type] += 1
                # 변경유형: text_diff 우선
                change_type = diff_meta.get("변경유형", "") or jo_data.get("조문제개정유형", "")
                changed[jo_key] = {
                    "조문제목": title,
                    "조문내용": content,
                    "변경유형": change_type,
                }
            versions[law_type][pub] = {
                "공포일자": pub,
                "시행일자": ver.get("시행일자", ""),
                "제개정구분": ver.get("제개정구분", ""),
                "제개정이유": ver.get("제개정이유", "") or "",
                "변경조문": changed,
                "부칙_시행일": parse_addenda(addenda_by_pub[law_type].get(pub, []), pub),
            }
        print(f"  {law_type}: {len(versions[law_type])}개 버전 (API 거짓음성 구제 {rescued[law_type]}건)")

    # 인덱스
    pubdate_to_law_pubs = set(versions["법률"].keys())
    pubdate_to_decree_pubs = set(versions["시행령"].keys())
    law_effdate_to_pubs = defaultdict(list)
    for pub, lver in versions["법률"].items():
        eff = lver.get("시행일자", "")
        if eff:
            law_effdate_to_pubs[eff].append(pub)
    decree_effdate_to_pubs = defaultdict(list)
    for pub, dver in versions["시행령"].items():
        eff = dver.get("시행일자", "")
        if eff:
            decree_effdate_to_pubs[eff].append(pub)

    # ─────────────────────────────────────────────────────
    # 3. 변경조문 매핑 (sub_to_law / law_to_sub) — 보조 신호
    # ─────────────────────────────────────────────────────
    sub_to_law = {"시행령": defaultdict(set), "시행규칙": defaultdict(set)}
    rule_to_decree = defaultdict(set)  # 시행규칙 조문 → 시행령 조문 매핑
    law_to_sub = defaultdict(lambda: {"시행령": set(), "시행규칙": set()})

    for entry in mapdata["매핑"]:
        jo = entry["법률_조키"]
        for pm in entry.get("항별_매핑", []):
            for d in pm.get("시행령", []):
                sub_to_law["시행령"][d["조키"]].add(jo)
                law_to_sub[jo]["시행령"].add(d["조키"])
                for r in d.get("시행규칙", []):
                    sub_to_law["시행규칙"][r["조키"]].add(jo)
                    law_to_sub[jo]["시행규칙"].add(r["조키"])
                    rule_to_decree[r["조키"]].add(d["조키"])
            for r in pm.get("시행규칙_직접", []):
                sub_to_law["시행규칙"][r["조키"]].add(jo)
                law_to_sub[jo]["시행규칙"].add(r["조키"])
        for g in entry.get("조문전체_매핑", []):
            if g["법령유형"] == "시행령":
                sub_to_law["시행령"][g["조키"]].add(jo)
            elif g["법령유형"] == "시행규칙":
                sub_to_law["시행규칙"][g["조키"]].add(jo)

    # ─────────────────────────────────────────────────────
    # 4. IDF 계산 — 빈출 키워드 가중치 자동 하향
    # ─────────────────────────────────────────────────────
    print("\n📌 4. IDF (역문서빈도) 계산...")
    # 문서 = 각 버전의 (제개정이유 + 변경조문 제목)
    docs = []
    for law_type in ["법률", "시행령", "시행규칙"]:
        for pub, ver in versions[law_type].items():
            text = ver.get("제개정이유", "")
            for jo in ver.get("변경조문", {}).values():
                text += " " + jo.get("조문제목", "")
            docs.append(extract_keywords(text))
    N = len(docs) or 1
    df = defaultdict(int)
    for d in docs:
        for kw in d:
            df[kw] += 1
    # IDF: 자주 등장할수록 작음. 1회 등장이면 log(N)에 가까운 큰 값
    idf = {kw: math.log((N + 1) / (cnt + 1)) + 1.0 for kw, cnt in df.items()}
    print(f"  키워드 종수: {len(idf)}, 문서 수: {N}")

    # ─────────────────────────────────────────────────────
    # 5. 매칭 헬퍼
    # ─────────────────────────────────────────────────────
    # 매칭 결과: sub_versions의 ver dict에 _parent_type, _parent_pub, _match_method, _match_evidence 추가
    matched_decree_pubs = set()  # 매칭 완료된 시행령 공포일
    matched_rule_pubs = set()

    def set_parent(sub_type, ver, parent_type, parent_pub, method, evidence):
        sub_pub = ver["공포일자"]
        if sub_type == "시행령":
            if sub_pub in matched_decree_pubs:
                return False
            matched_decree_pubs.add(sub_pub)
        else:
            if sub_pub in matched_rule_pubs:
                return False
            matched_rule_pubs.add(sub_pub)
        ver["_parent_type"] = parent_type  # "법률" or "시행령"
        ver["_parent_pub"] = parent_pub
        ver["_match_method"] = method  # "공포번호", "공포일자", "시행일자", "텍스트분석"
        ver["_match_evidence"] = evidence
        return True

    # ─────────────────────────────────────────────────────
    # Stage 1: 공포번호 매칭
    # ─────────────────────────────────────────────────────
    print("\n📌 Stage 1: 공포번호 매칭...")
    s1d = s1r_law = s1r_dec = 0
    for sub_type, sub_vers in [("시행령", versions["시행령"]), ("시행규칙", versions["시행규칙"])]:
        for pub, ver in sub_vers.items():
            reason = ver["제개정이유"]
            # 1. 법률 공포번호 우선 시도
            for no in LAW_NO_PAT.findall(reason):
                lp = law_pubno_to_pubdate.get(norm_pubno(no))
                if lp and lp in pubdate_to_law_pubs:
                    if set_parent(sub_type, ver, "법률", lp, "공포번호", f"법률 제{no}호"):
                        if sub_type == "시행령": s1d += 1
                        else: s1r_law += 1
                    break
            else:
                # 2. 시행규칙만: 대통령령 공포번호 시도
                if sub_type == "시행규칙":
                    for no in DECREE_NO_PAT.findall(reason):
                        dp = decree_pubno_to_pubdate.get(norm_pubno(no))
                        if dp and dp in pubdate_to_decree_pubs:
                            if set_parent(sub_type, ver, "시행령", dp, "공포번호", f"대통령령 제{no}호"):
                                s1r_dec += 1
                            break
    print(f"  시행령→법률: {s1d}건")
    print(f"  시행규칙→법률: {s1r_law}건, 시행규칙→시행령: {s1r_dec}건")

    # ─────────────────────────────────────────────────────
    # Stage 2: 공포일자 매칭
    # ─────────────────────────────────────────────────────
    print("\n📌 Stage 2: 공포일자 매칭...")
    s2d = s2r_law = s2r_dec = 0
    for sub_type, sub_vers in [("시행령", versions["시행령"]), ("시행규칙", versions["시행규칙"])]:
        already = matched_decree_pubs if sub_type == "시행령" else matched_rule_pubs
        for pub, ver in sub_vers.items():
            if ver["공포일자"] in already:
                continue
            reason = ver["제개정이유"]
            dates = parse_dates_in_text(reason, PUBDATE_PAT)
            matched_here = False
            # 1. 법률 공포일자 매칭 (시행규칙도 법률 우선)
            for ymd, disp in dates:
                if ymd in pubdate_to_law_pubs:
                    if set_parent(sub_type, ver, "법률", ymd, "공포일자", f"{disp} 공포"):
                        if sub_type == "시행령": s2d += 1
                        else: s2r_law += 1
                        matched_here = True
                    break
            # 2. 시행규칙만: 시행령 공포일자 매칭
            if not matched_here and sub_type == "시행규칙":
                for ymd, disp in dates:
                    if ymd in pubdate_to_decree_pubs:
                        if set_parent(sub_type, ver, "시행령", ymd, "공포일자", f"{disp} 공포(시행령)"):
                            s2r_dec += 1
                        break
    print(f"  시행령→법률: {s2d}건")
    print(f"  시행규칙→법률: {s2r_law}건, 시행규칙→시행령: {s2r_dec}건")

    # ─────────────────────────────────────────────────────
    # Stage 3: 시행일자 매칭 (모호하지 않은 단일 후보만)
    #   3a) 제개정이유 텍스트에 시행일자 패턴 명시
    #   3b) 자식 자신의 시행일 == 부모 시행일 (단일 후보) + 변경조문 매핑 교차
    #       → "시간 간격"이 아니라 "정확 일치 + 의미 연결" 객관 자료
    # ─────────────────────────────────────────────────────
    print("\n📌 Stage 3: 시행일자 매칭...")

    def pick_unique_amend(pubs, vmap):
        """동일 시행일에 여러 법령 → 일부개정 단일 또는 전체 단일일 때만 채택"""
        amend = [p for p in pubs if vmap[p].get("제개정구분") == "일부개정"]
        if len(amend) == 1:
            return amend[0]
        if len(pubs) == 1:
            return pubs[0]
        return None

    # 자식 변경조문 → 부모 변경조문 매핑 교차 검증 헬퍼
    def has_change_overlap(sub_type, child_changed, parent_changed_keys, target_type):
        """자식 변경조문이 매핑상 부모 변경조문과 1개 이상 연결되는지"""
        if not child_changed or not parent_changed_keys:
            return False
        for ck in child_changed:
            if target_type == "법률":
                related = sub_to_law.get(sub_type, {}).get(ck, set())
            else:  # 시행령
                related = rule_to_decree.get(ck, set())
            if related & parent_changed_keys:
                return True
        return False

    s3d = s3r_law = s3r_dec = 0
    s3b_d = s3b_r_law = s3b_r_dec = 0  # 3b 카운트

    for sub_type, sub_vers in [("시행령", versions["시행령"]), ("시행규칙", versions["시행규칙"])]:
        already = matched_decree_pubs if sub_type == "시행령" else matched_rule_pubs
        for pub, ver in sub_vers.items():
            if ver["공포일자"] in already:
                continue
            reason = ver["제개정이유"]
            child_changed = set(ver.get("변경조문", {}).keys())

            # 3a) 제개정이유 텍스트의 시행일자 패턴
            dates = parse_dates_in_text(reason, EFFDATE_PAT)
            matched_here = False
            for ymd, disp in dates:
                target = pick_unique_amend(law_effdate_to_pubs.get(ymd, []), versions["법률"])
                if target:
                    if set_parent(sub_type, ver, "법률", target, "시행일자", f"{disp} 시행"):
                        if sub_type == "시행령": s3d += 1
                        else: s3r_law += 1
                        matched_here = True
                    break
            if not matched_here and sub_type == "시행규칙":
                for ymd, disp in dates:
                    target = pick_unique_amend(decree_effdate_to_pubs.get(ymd, []), versions["시행령"])
                    if target:
                        if set_parent(sub_type, ver, "시행령", target, "시행일자", f"{disp} 시행(시행령)"):
                            s3r_dec += 1
                            matched_here = True
                        break

            if matched_here:
                continue

            # 3b) 자식 시행일 == 부모 시행일 (단일 후보) + 변경조문 매핑 교차
            # 조건: 도로교통법 언급 있음(텍스트 의미적 연결의 최소 보장)
            if not LAWNAME_PAT.search(reason):
                continue
            child_eff = ver.get("시행일자", "")
            if not child_eff:
                continue

            # 법률 후보: 자식 시행일과 같은 시행일을 가진 법률 (단일 일부개정)
            target = pick_unique_amend(law_effdate_to_pubs.get(child_eff, []), versions["법률"])
            if target:
                parent_changed = set(versions["법률"][target].get("변경조문", {}).keys())
                if has_change_overlap(sub_type, child_changed, parent_changed, "법률"):
                    if set_parent(sub_type, ver, "법률", target, "시행일자",
                                  f"자식시행일={child_eff} 부모시행일 일치 + 변경조문 매핑교차"):
                        if sub_type == "시행령": s3b_d += 1
                        else: s3b_r_law += 1
                        continue

            # 시행규칙 → 시행령: 자식 시행일과 같은 시행일의 시행령 단일 후보
            if sub_type == "시행규칙":
                target = pick_unique_amend(decree_effdate_to_pubs.get(child_eff, []), versions["시행령"])
                if target:
                    parent_changed = set(versions["시행령"][target].get("변경조문", {}).keys())
                    if has_change_overlap("시행규칙", child_changed, parent_changed, "시행령"):
                        if set_parent(sub_type, ver, "시행령", target, "시행일자",
                                      f"자식시행일={child_eff} 시행령시행일 일치 + 매핑교차"):
                            s3b_r_dec += 1

    print(f"  3a) 텍스트 시행일자 명시 — 시행령→법률: {s3d}, 시행규칙→법률: {s3r_law}, →시행령: {s3r_dec}")
    print(f"  3b) 자식↔부모 시행일 일치 — 시행령→법률: {s3b_d}, 시행규칙→법률: {s3b_r_law}, →시행령: {s3b_r_dec}")

    # ─────────────────────────────────────────────────────
    # Stage 4: 텍스트 의미 매칭 (다중 신호 종합)
    # 신호:
    #   (a) 자식 변경조문 제목 → 부모 제개정이유 substring 매칭 (강한 신호)
    #   (b) 숫자+한글 단위(75세, 3년 등) 매칭 (결정적 신호)
    #   (c) 변경조문 매핑 교차 precision (큰 부모 자동 페널티)
    #   (d) IDF 가중 키워드 substring + precision 보정 (보조)
    # 부모/자식 모두 타법개정이면 후보 제외
    # ─────────────────────────────────────────────────────
    print("\n📌 Stage 4: 텍스트 의미 매칭 (다중 신호)...")

    # 부모별 키워드 캐시
    def build_kw_cache(parent_versions):
        cache = {}
        for p, v in parent_versions.items():
            if v.get("제개정구분") == "타법개정":
                continue
            text_kws = extract_keywords(v.get("제개정이유", ""))
            title_kws = set()
            for jo in v.get("변경조문", {}).values():
                title_kws.update(extract_keywords(jo.get("조문제목", "")))
            cache[p] = (text_kws, title_kws)
        return cache

    law_kw_cache = build_kw_cache(versions["법률"])
    decree_kw_cache = build_kw_cache(versions["시행령"])

    THRESHOLD = 25.0  # 다중 신호 종합 점수 임계값 (추가 신호로 점수 분포 상향)
    TOP_IDF_K = 8     # 자식 텍스트에서 추출할 상위 희소 키워드 개수

    def compute_multi_signal_score(child_titles, child_text, child_mapped_parent_keys,
                                    parent_ver, parent_text_kws, parent_title_kws):
        """다중 신호 종합 점수 + 필수조건 검증
        Returns: (score, evidence, passes_required)
        """
        parent_reason = parent_ver.get("제개정이유", "") or ""
        parent_changed = set(parent_ver.get("변경조문", {}).keys())

        # (a) 자식 제목 강 키워드 → 부모 제개정이유 substring 매칭
        child_strong_kws = extract_strong_title_keywords(child_titles)
        title_matches = [kw for kw in child_strong_kws if kw in parent_reason]
        title_count = len(title_matches)
        title_ratio = title_count / max(1, len(child_strong_kws))

        # (b) 숫자+한글 단위 매칭 (결정적 신호: 75세, 3년 등)
        num_kws = [kw for kw in child_strong_kws if any(c.isdigit() for c in kw)]
        num_matched = [kw for kw in num_kws if kw in parent_reason]

        # (c) 변경조문 매핑 교차 (절대값 + 정밀도)
        map_overlap = child_mapped_parent_keys & parent_changed
        map_count = len(map_overlap)
        map_precision = map_count / max(1, len(parent_changed))

        # (d) IDF 가중 키워드 substring + precision 보정
        all_parent_kws = parent_text_kws | parent_title_kws
        idf_matched = [kw for kw in all_parent_kws if kw in child_text]
        idf_score = sum(idf.get(kw, 1.0) + (3.0 if kw in parent_title_kws else 0) for kw in idf_matched)
        kw_precision = len(idf_matched) / max(1, len(all_parent_kws))
        idf_weighted = idf_score * kw_precision

        # (e) 자식 텍스트 IDF 상위 키워드 → 부모 제개정이유 매칭 (핵심 신호)
        # "개인형이동장치", "교통체계" 같은 희소 단어가 부모에 있는지 — 결정적
        child_kws = extract_keywords(child_text)
        child_top_idf = sorted(child_kws, key=lambda k: -idf.get(k, 0))[:TOP_IDF_K]
        top_matched = [kw for kw in child_top_idf if kw in parent_reason]
        top_match_idf_sum = sum(idf.get(kw, 1.0) for kw in top_matched)
        top_match_ratio = len(top_matched) / max(1, len(child_top_idf))

        # (f) 매우 희소한 키워드(IDF >= 4.0) 매칭 — 도메인 특수 어휘 (결정적)
        # "개인형", "이동장치", "교통체계", "실외이동로봇" 같은 신규/특수 명사구
        very_rare_matched = [kw for kw in top_matched if idf.get(kw, 0) >= 4.0]

        # 종합 점수: 절대값과 비율 신호를 균형있게 결합
        score = (
            title_ratio * 20         # (a) 비율 (큰 부모는 자연 페널티)
            + title_count * 2         # (a) 절대값 (작은 부모 보호)
            + len(num_matched) * 15   # (b) 숫자+단위 결정적
            + map_count * 3           # (c) 매핑 절대값
            + min(map_precision, 0.3) * 30  # (c) 정밀도 (상한 0.3)
            + idf_weighted            # (d) IDF 보조
            + top_match_ratio * 25    # (e) 자식 핵심 키워드 → 부모 매칭률
            + top_match_idf_sum * 1.5 # (e) 매칭된 핵심 키워드 IDF 합 (희소할수록 강함)
            + len(very_rare_matched) * 10  # (f) 매우 희소한 도메인 키워드 매칭 (결정적)
        )

        # 필수 조건: 신호가 실제로 의미 있어야 매칭 (오매칭 방지)
        # - 자식 제목이 부모 이유에 2개 이상 등장하거나
        # - 숫자 단위가 1개 이상 매칭되거나
        # - 자식 핵심 키워드 2개 이상 매칭 + IDF 합 6 이상 (희소 매칭)
        # - 매핑교차 3개 이상 + 정밀도 0.05 이상
        passes = (
            title_count >= 2
            or len(num_matched) >= 1
            or (len(top_matched) >= 2 and top_match_idf_sum >= 6.0)
            or (map_count >= 3 and map_precision >= 0.05)
        )

        ev = (f"점수={score:.1f} | "
              f"제목→이유={title_count}/{len(child_strong_kws)}({','.join(title_matches[:3])}) "
              f"매핑={map_count}/{len(parent_changed)} "
              f"숫자={','.join(num_matched) if num_matched else '없음'} "
              f"핵심키워드={len(top_matched)}/{len(child_top_idf)}({','.join(top_matched[:3])}) "
              f"희소={','.join(very_rare_matched) if very_rare_matched else '없음'}")
        return score, ev, passes

    # 자식별로 매핑된 부모 조문 키 미리 계산
    def child_mapped_keys(sub_type, ver):
        keys = set()
        if sub_type == "시행령":
            mapper = sub_to_law["시행령"]
        else:
            mapper = sub_to_law["시행규칙"]
        for sk in ver.get("변경조문", {}).keys():
            keys.update(mapper.get(sk, set()))
        return keys

    def child_mapped_decree_keys(rule_ver):
        keys = set()
        for rk in rule_ver.get("변경조문", {}).keys():
            keys.update(rule_to_decree.get(rk, set()))
        return keys

    s4d = s4r_law = s4r_dec = 0
    for sub_type, sub_vers in [("시행령", versions["시행령"]), ("시행규칙", versions["시행규칙"])]:
        already = matched_decree_pubs if sub_type == "시행령" else matched_rule_pubs
        for pub, ver in sub_vers.items():
            if ver["공포일자"] in already:
                continue
            if ver.get("제개정구분") == "타법개정":
                continue
            reason = ver["제개정이유"]
            if not LAWNAME_PAT.search(reason):
                continue

            # 자식 원문(키워드 substring 검색용) + 변경조문 제목들
            child_titles = [jo.get("조문제목", "") for jo in ver.get("변경조문", {}).values()]
            child_text = reason + " " + " ".join(child_titles)
            child_to_law = child_mapped_keys(sub_type, ver)

            best = None  # (score, parent_type, parent_pub, evidence)

            # 후보 1: 법률
            for lpub, (text_kws, title_kws) in law_kw_cache.items():
                lver = versions["법률"][lpub]
                score, ev, passes = compute_multi_signal_score(
                    child_titles, child_text, child_to_law,
                    lver, text_kws, title_kws,
                )
                if passes and score >= THRESHOLD and (best is None or score > best[0]):
                    best = (score, "법률", lpub, ev)

            # 후보 2: 시행규칙만 → 시행령
            if sub_type == "시행규칙":
                child_to_decree = child_mapped_decree_keys(ver)
                for dpub, (text_kws, title_kws) in decree_kw_cache.items():
                    dver = versions["시행령"][dpub]
                    score, ev, passes = compute_multi_signal_score(
                        child_titles, child_text, child_to_decree,
                        dver, text_kws, title_kws,
                    )
                    if passes and score >= THRESHOLD and (best is None or score > best[0]):
                        best = (score, "시행령", dpub, ev)

            if best:
                _, ptype, ppub, ev = best
                if set_parent(sub_type, ver, ptype, ppub, "텍스트분석", ev):
                    if sub_type == "시행령": s4d += 1
                    elif ptype == "법률": s4r_law += 1
                    else: s4r_dec += 1

    print(f"  시행령→법률: {s4d}건")
    print(f"  시행규칙→법률: {s4r_law}건, 시행규칙→시행령: {s4r_dec}건")

    # 최종 통계
    total_d = len(versions["시행령"])
    total_r = len(versions["시행규칙"])
    print(f"\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  시행령 매칭: {len(matched_decree_pubs)}/{total_d}건 (미매칭 {total_d - len(matched_decree_pubs)})")
    print(f"  시행규칙 매칭: {len(matched_rule_pubs)}/{total_r}건 (미매칭 {total_r - len(matched_rule_pubs)})")

    # ─────────────────────────────────────────────────────
    # 5.5. 별표 → 법률 조문 매핑 인덱스 (6단계 전에 미리 빌드 — make_sub_entry에서 사용)
    # 별표 제목에서 모법 조문 추출 → sub_to_law로 법률 조문까지 사슬 연결
    # 본문 인용 "법 제X조"도 추가 매핑
    # ─────────────────────────────────────────────────────
    print("\n📌 5.5. 별표 → 법률 조문 매핑 구축 (제목 사슬 + 본문 인용)...")
    law_to_tables = defaultdict(dict)  # 법률조문키 → {별표키: 항목}
    title_count = ref_count = 0
    table_unmapped = 0

    def add_table_entry(law_art, sub_type, tname, title, parent_arts, source):
        key = f"{sub_type}/{tname}"
        if key not in law_to_tables[law_art]:
            law_to_tables[law_art][key] = {
                "법령유형": sub_type,
                "별표명": tname,
                "제목": title,
                "모법조문": parent_arts,
                "매핑출처": [source],
            }
        else:
            srcs = law_to_tables[law_art][key]["매핑출처"]
            if source not in srcs:
                srcs.append(source)

    for sub_type in ["시행령", "시행규칙"]:
        for tname, tdata in attached_tables.get(sub_type, {}).items():
            if tdata.get("구분") != "별표":
                continue
            title = tdata.get("제목", "")
            if "삭제" in title:
                continue
            content = tdata.get("내용", "") or ""
            parent_arts = parse_table_parent_articles(title)
            linked_via_title = set()
            for pa in parent_arts:
                linked_via_title |= sub_to_law.get(sub_type, {}).get(pa, set())
            for law_art in linked_via_title:
                add_table_entry(law_art, sub_type, tname, title, parent_arts, "제목사슬")
            if linked_via_title:
                title_count += 1
            cited_arts = set(LAW_REF_IN_TABLE.findall(content))
            for law_art in cited_arts:
                add_table_entry(law_art, sub_type, tname, title, parent_arts, "본문인용")
            if cited_arts:
                ref_count += 1
            if not linked_via_title and not cited_arts:
                table_unmapped += 1

    law_to_tables_final = {jo: list(d.values()) for jo, d in law_to_tables.items()}
    print(f"  제목사슬 {title_count}건, 본문인용 {ref_count}건, 매핑실패 {table_unmapped}건")
    print(f"  관련 별표 보유 법률 조문 {len(law_to_tables_final)}개")

    # ─────────────────────────────────────────────────────
    # 6. 캐스케이드 이벤트 구축 (법률 중심)
    # 시행규칙은 직접부모(법률 또는 시행령) 정보 보존.
    # 시행령에 매칭된 시행규칙은 그 시행령의 부모 법률 이벤트에 함께 표시.
    # ─────────────────────────────────────────────────────
    print("\n📌 6. 캐스케이드 이벤트 구축...")

    # 시행령 공포일 → 부모 법률 공포일 (간접 연결용)
    decree_pub_to_law_pub = {}
    for pub, dver in versions["시행령"].items():
        if dver.get("_parent_type") == "법률":
            decree_pub_to_law_pub[pub] = dver["_parent_pub"]

    # 법률 공포일 → 직접 매칭된 시행령 리스트
    law_to_decrees = defaultdict(list)
    for pub, dver in versions["시행령"].items():
        if dver.get("_parent_type") == "법률":
            law_to_decrees[dver["_parent_pub"]].append(dver)

    # 법률 공포일 → 시행규칙 리스트 (직접 또는 시행령 경유 간접)
    law_to_rules = defaultdict(list)
    for pub, rver in versions["시행규칙"].items():
        ptype = rver.get("_parent_type")
        if ptype == "법률":
            law_to_rules[rver["_parent_pub"]].append(rver)
        elif ptype == "시행령":
            # 시행령의 부모 법률을 따라간다 (없으면 별도 표시 필요)
            decree_pub = rver["_parent_pub"]
            law_pub = decree_pub_to_law_pub.get(decree_pub)
            if law_pub:
                law_to_rules[law_pub].append(rver)

    # 매칭방법 → 신뢰도 등급
    # ★★★: 객관 자료 (공포번호/공포일자/시행일자) — 사실상 확정
    # ★★ : 텍스트 의미 분석 — 추정 (검증된 6건은 정확하나 일반적 신뢰도 표시는 보수적)
    # 미매칭 : 어떤 단서도 없음 — 사용자 수동 확인 필요
    METHOD_TO_TRUST = {
        "공포번호": "★★★",
        "공포일자": "★★★",
        "시행일자": "★★★",
        "텍스트분석": "★★",
    }

    # 시점별 별표 변경 인덱스: (sub_type, 공포일) → [{별표명, 제목, 변경유형, 이전길이, 이후길이, PDF URL}]
    table_changes_at_pub = {"시행령": defaultdict(list), "시행규칙": defaultdict(list)}
    for sub_type in ["시행령", "시행규칙"]:
        for tname, changes in attached_diff.get(sub_type, {}).items():
            for ch in changes:
                if not tname.startswith("별표"):
                    continue
                table_changes_at_pub[sub_type][ch["공포일자"]].append({
                    "별표명": tname,
                    "제목": ch.get("제목", ""),
                    "변경유형": ch.get("변경유형", ""),
                    "이전길이": len(ch.get("이전", "")),
                    "이후길이": len(ch.get("이후", "")),
                    "이전PDF_URL": ch.get("이전PDF_URL", ""),
                    "이후PDF_URL": ch.get("이후PDF_URL", ""),
                    "이전공포일": ch.get("이전공포일", ""),
                })

    def make_sub_entry(sub_ver, sub_type, parent_law_ver):
        """시행령/시행규칙 항목을 캐스케이드 이벤트용 dict로 변환"""
        linked = []
        other = []
        law_changed_keys = set(parent_law_ver.get("변경조문", {}).keys()) if parent_law_ver else set()
        for sk, sd in sub_ver["변경조문"].items():
            related_law = sub_to_law[sub_type].get(sk, set()) & law_changed_keys
            if related_law:
                linked.append({
                    "조문키": sk,
                    "조문제목": sd["조문제목"],
                    "조문내용": sd["조문내용"],
                    "변경유형": sd["변경유형"],
                    "연결법률조문": sorted(related_law),
                })
            else:
                other.append({
                    "조문키": sk,
                    "조문제목": sd["조문제목"],
                    "변경유형": sd["변경유형"],
                })
        method = sub_ver.get("_match_method", "")
        # 이번 공포일에 변경된 별표 + 각 별표가 어느 법률 조문과 매핑되는지 부착
        table_changes_raw = table_changes_at_pub[sub_type].get(sub_ver["공포일자"], [])
        table_changes = []
        for tc in table_changes_raw:
            # 이 별표 → 법률 조문 (cascade 8단계의 law_to_tables 역인덱스 활용)
            linked_law_arts = []
            for jo, tlist in law_to_tables.items():
                for t in tlist.values() if isinstance(tlist, dict) else tlist:
                    if t["법령유형"] == sub_type and t["별표명"] == tc["별표명"]:
                        linked_law_arts.append(jo)
                        break
            table_changes.append({**tc, "연결법률조문": sorted(set(linked_law_arts))})
        return {
            "공포일자": sub_ver["공포일자"],
            "시행일자": sub_ver["시행일자"],
            "제개정구분": sub_ver["제개정구분"],
            "제개정이유": sub_ver["제개정이유"],
            "연결변경조문": linked,
            "기타변경조문": other,
            "별표변경": table_changes,
            "매칭방법": method,
            "매칭근거": sub_ver.get("_match_evidence", ""),
            "신뢰도": METHOD_TO_TRUST.get(method, ""),
            "직접부모": sub_ver.get("_parent_type", ""),
            "직접부모공포일": sub_ver.get("_parent_pub", ""),
            "부칙_시행일": sub_ver.get("부칙_시행일"),
        }

    def make_unmatched_entry(sub_ver, sub_type):
        """미매칭 시행령/시행규칙 항목 — 사용자가 수동 확인할 수 있도록 정보 보존"""
        return {
            "공포일자": sub_ver["공포일자"],
            "시행일자": sub_ver["시행일자"],
            "제개정구분": sub_ver["제개정구분"],
            "제개정이유": sub_ver["제개정이유"],
            "변경조문": [
                {
                    "조문키": sk,
                    "조문제목": sd["조문제목"],
                    "조문내용": sd["조문내용"],
                    "변경유형": sd["변경유형"],
                    # 매핑상 연결되는 법률 조문 (참고용 — 부모 매칭 단서)
                    "참고_연결법률조문": sorted(sub_to_law[sub_type].get(sk, set())),
                }
                for sk, sd in sub_ver["변경조문"].items()
            ],
            "신뢰도": "미매칭",
            "안내": "관련 법률을 자동 매칭하지 못했습니다. 제개정이유와 변경조문을 직접 확인하세요.",
            "부칙_시행일": sub_ver.get("부칙_시행일"),
        }

    events = []
    for law_pub, lver in sorted(versions["법률"].items(), reverse=True):
        event = {
            "기준공포일": law_pub,
            "법률": {
                "공포일자": lver["공포일자"],
                "시행일자": lver["시행일자"],
                "제개정구분": lver["제개정구분"],
                "제개정이유": lver["제개정이유"],
                "변경조문": [],
                "부칙_시행일": lver.get("부칙_시행일"),
            },
            "시행령": [],
            "시행규칙": [],
        }
        for jo_key, jo_data in lver["변경조문"].items():
            event["법률"]["변경조문"].append({
                "조문키": jo_key,
                "조문제목": jo_data["조문제목"],
                "조문내용": jo_data["조문내용"],
                "변경유형": jo_data["변경유형"],
                "연결_시행령": sorted(law_to_sub.get(jo_key, {}).get("시행령", set())),
                "연결_시행규칙": sorted(law_to_sub.get(jo_key, {}).get("시행규칙", set())),
            })
        for dver in law_to_decrees.get(law_pub, []):
            event["시행령"].append(make_sub_entry(dver, "시행령", lver))
        for rver in law_to_rules.get(law_pub, []):
            event["시행규칙"].append(make_sub_entry(rver, "시행규칙", lver))
        events.append(event)

    has_d = sum(1 for e in events if e["시행령"])
    has_r = sum(1 for e in events if e["시행규칙"])
    has_both = sum(1 for e in events if e["시행령"] and e["시행규칙"])
    print(f"  ✅ {len(events)}개 이벤트 (시행령 연쇄 {has_d}, 시행규칙 연쇄 {has_r}, 양쪽 {has_both})")

    # ─────────────────────────────────────────────────────
    # 6.5. 미매칭 시행령/시행규칙 컬렉션 (사용자 수동 확인용)
    # ─────────────────────────────────────────────────────
    print("\n📌 6.5. 미매칭 시행령/시행규칙 정리...")
    unmatched_decree = []
    for pub, dver in sorted(versions["시행령"].items(), reverse=True):
        if pub not in matched_decree_pubs:
            unmatched_decree.append(make_unmatched_entry(dver, "시행령"))
    unmatched_rule = []
    for pub, rver in sorted(versions["시행규칙"].items(), reverse=True):
        if pub not in matched_rule_pubs:
            unmatched_rule.append(make_unmatched_entry(rver, "시행규칙"))
    print(f"  미매칭 시행령 {len(unmatched_decree)}건, 시행규칙 {len(unmatched_rule)}건")

    # 매칭 신뢰도 통계
    trust_stats = {"★★★": 0, "★★": 0}
    for e in events:
        for s in e["시행령"] + e["시행규칙"]:
            t = s.get("신뢰도", "")
            if t in trust_stats:
                trust_stats[t] += 1
    print(f"  신뢰도 ★★★(객관): {trust_stats['★★★']}건, ★★(텍스트분석 추정): {trust_stats['★★']}건")

    # ─────────────────────────────────────────────────────
    # 7. 조문별 이벤트 인덱스 + 저장
    # ─────────────────────────────────────────────────────
    # 시행령·시행규칙 → 매핑된 법률 조문 사전 (인덱스 확장용)
    # 시행령·시행규칙이 단독 변경된 시점도 매핑된 법률 조문 연혁 탭에 표시되도록.
    sub_to_law_jo = {}  # (법령유형, 조문키) → 법률 조문키
    for entry in mapdata.get("매핑", []):
        law_jo = entry.get("법률_조키")
        if not law_jo:
            continue
        for hh in entry.get("항별_매핑", []):
            for r in hh.get("시행령", []):
                sub_to_law_jo.setdefault(("시행령", r.get("조키")), law_jo)
            for r in hh.get("시행규칙_직접", []):
                sub_to_law_jo.setdefault(("시행규칙", r.get("조키")), law_jo)
        for c in entry.get("조문전체_매핑", []):
            st = c.get("법령유형")
            sj = c.get("조키")
            if st and sj:
                sub_to_law_jo.setdefault((st, sj), law_jo)

    # 기타변경조문 중 매핑된 법률 조문이 있는 것은 연결변경조문으로 자동 이동
    # → viewer.html이 연결변경조문만 표시하므로, 매핑 가능한 변경은 모두 연결변경조문으로
    moved_count = 0
    for event in events:
        for sub_type_key in ["시행령", "시행규칙"]:
            for sub in event.get(sub_type_key, []):
                etc_remaining = []
                for art in sub.get("기타변경조문", []):
                    jo_key = art.get("조문키")
                    law_jo = sub_to_law_jo.get((sub_type_key, jo_key))
                    if law_jo:
                        art_new = dict(art)
                        art_new["연결법률조문"] = [law_jo]
                        sub.setdefault("연결변경조문", []).append(art_new)
                        moved_count += 1
                    else:
                        etc_remaining.append(art)
                sub["기타변경조문"] = etc_remaining
    print(f"  📌 기타변경조문 → 연결변경조문 이동: {moved_count}건 (mapdata 매핑 활용)")

    article_events = defaultdict(list)
    for i, event in enumerate(events):
        # 한 이벤트당 한 조문에 중복 추가 방지
        jos_for_event = set()
        # 법률 자체 변경
        for art in event["법률"]["변경조문"]:
            jos_for_event.add(art["조문키"])
        # 시행령 변경 → 매핑된 법률 조문
        # 연결변경조문에는 이미 "연결법률조문" 필드 있음. 기타변경조문은 sub_to_law_jo로 매핑.
        for d in event.get("시행령", []):
            for art in d.get("연결변경조문", []):
                for law_jo in art.get("연결법률조문", []):
                    jos_for_event.add(law_jo)
            for art in d.get("기타변경조문", []):
                law_jo = sub_to_law_jo.get(("시행령", art.get("조문키")))
                if law_jo:
                    jos_for_event.add(law_jo)
        # 시행규칙 변경 → 매핑된 법률 조문
        for r in event.get("시행규칙", []):
            for art in r.get("연결변경조문", []):
                for law_jo in art.get("연결법률조문", []):
                    jos_for_event.add(law_jo)
            for art in r.get("기타변경조문", []):
                law_jo = sub_to_law_jo.get(("시행규칙", art.get("조문키")))
                if law_jo:
                    jos_for_event.add(law_jo)
        for jo in jos_for_event:
            article_events[jo].append(i)
    print(f"\n📌 7. 조문별 이벤트 인덱스: {len(article_events)}개 조문 (시행령·시행규칙 매핑 확장 포함)")

    result = {
        "생성일시": datetime.now().isoformat(),
        "매칭방법": "공포번호+공포일자+시행일자+텍스트분석(IDF가중) — 시간 기반 미사용",
        "신뢰도등급": {
            "★★★": "객관 자료(공포번호/공포일자/시행일자) 기반 — 사실상 확정",
            "★★": "텍스트 의미 분석 기반 — 추정 매칭, 검토 권장",
            "미매칭": "어떤 단서도 없음 — 사용자 수동 확인 필요",
        },
        "이벤트": events,
        "미매칭_시행령": unmatched_decree,
        "미매칭_시행규칙": unmatched_rule,
        "조문별이벤트인덱스": dict(article_events),
        "법률조문별_관련별표": law_to_tables_final,
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    size_mb = os.path.getsize(OUTPUT_PATH) / (1024 * 1024)
    print(f"💾 저장: {OUTPUT_PATH} ({size_mb:.1f}MB)")

    # ─────────────────────────────────────────────────────
    # 검증
    # ─────────────────────────────────────────────────────
    print("\n=== 검증 (주요 케이스) ===")
    for pub in ["20231024", "20171024", "20180327", "20191224"]:
        for e in events:
            if e["기준공포일"] == pub:
                lw = e["법률"]
                print(f"\n법률 {pub} ({lw['제개정구분']}) 시행={lw['시행일자']}")
                for d in e["시행령"]:
                    print(f"  시행령 {d['공포일자']} 시행={d['시행일자']} ({d['제개정구분']}) [{d['매칭방법']}] {d['매칭근거'][:60]}")
                for r in e["시행규칙"]:
                    parent = f"부모={r['직접부모']}({r['직접부모공포일']})" if r['직접부모'] != "법률" else ""
                    print(f"  시행규칙 {r['공포일자']} 시행={r['시행일자']} ({r['제개정구분']}) [{r['매칭방법']}] {parent} {r['매칭근거'][:60]}")
                if not e["시행령"] and not e["시행규칙"]:
                    print("  (하위법령 매칭 없음)")
                break


if __name__ == "__main__":
    main()
