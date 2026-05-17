"""부칙(附則) 시행일 파싱 모듈.

법령 개정 시 부칙에 의해 같은 개정안 안에서도 조항별 시행일이 달라질 수 있다.
이 모듈은 부칙 텍스트에서 본문 시행일과 단서(다만 절)의 조문별 별도 시행일을 추출한다.

사용 예:
    from parse_addenda_effective import parse_addenda
    info = parse_addenda(addenda_list, public_date="20251230")
    # info["main_effective_date"] → "20251230"
    # info["exceptions"] → [{"articles":["44"],"effective_date":"20260630", ...}]
    # info["raw_text"] → 부칙 원문 (UI 표시용, 1500자 제한)

파싱 실패해도 raw_text는 항상 보존되므로 UI 에서 사용자 검증 가능.
"""

import re
from datetime import datetime
from dateutil.relativedelta import relativedelta


_RAW_TEXT_LIMIT = 1500

# "공포 후 N(개월|년|일)" 변형
_RELATIVE_PERIOD_RE = re.compile(
    r"공포(?:한\s*날|일)?(?:\s*후|로?부터)?\s*(\d+)\s*(개월|년|일)"
    r"\s*(?:이|을)?\s*(?:경과한|되는|지난|기산한)?"
)

# "YYYY년 MM월 DD일부터 시행"
_EXPLICIT_DATE_RE = re.compile(
    r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"
)

# "공포한 날부터 시행" (단순)
_PROMULGATE_DAY_RE = re.compile(r"공포(?:한\s*날|일)(?:로?부터)?\s*시행")

# 조문 번호 + 선택적 항·호: "제44조", "제44조의2", "제160조제4항제4호", "제2조제26호"
# 그룹: 1=조번호, 2=조가지번호, 3=항번호, 4=호번호, 5=호가지번호
_ARTICLE_DETAIL_RE = re.compile(
    r"제\s*(\d+)\s*조(?:의\s*(\d+))?"
    r"(?:제\s*(\d+)\s*항)?"
    r"(?:제\s*(\d+)\s*호(?:의\s*(\d+))?)?"
)

# 조문 범위: "제44조부터 제47조까지"
_ARTICLE_RANGE_RE = re.compile(
    r"제\s*(\d+)\s*조(?:부터|에서)\s*제\s*(\d+)\s*조(?:까지)?"
)

# 별표 번호: "별표 18", "별표 18의2"
_TABLE_RE = re.compile(r"별표\s*(\d+)(?:의\s*(\d+))?")


def _normalize_article_key(num: int, sub: int = None) -> str:
    """조문키 표기를 cascade 와 일치시킨다."""
    return f"{num}의{sub}" if sub else str(num)


def _extract_article_targets(text: str) -> tuple:
    """텍스트에서 조문 키와 항·호 상세를 추출. 범위 표기는 펼친다.

    Returns:
        (articles, article_items)
        articles: 조문 키 리스트 (중복 제거, 등장 순서 유지), 예 ["2", "96"]
        article_items: {조키: [항·호 상세문자열]}, 예 {"2": ["제26호"]}
                       조가 항·호 없이 통째로(bare) 인용되면 그 조키는 넣지 않는다
                       (= 조 전체가 별도 시행 대상이라는 뜻).
    """
    articles = []
    bare = set()       # 항·호 없이 조 단위로 인용된 조키
    detailed = {}      # 조키 → [상세문자열]

    # 범위 표기 "제44조부터 제47조까지" — 조 단위로 펼침
    for m in _ARTICLE_RANGE_RE.finditer(text):
        start, end = int(m.group(1)), int(m.group(2))
        if 1 <= start <= end <= 9999:
            for n in range(start, end + 1):
                articles.append(str(n))
                bare.add(str(n))

    consumed = {m.span() for m in _ARTICLE_RANGE_RE.finditer(text)}

    # 개별 조문 + 항·호 상세
    for m in _ARTICLE_DETAIL_RE.finditer(text):
        if any(s <= m.start() < e for s, e in consumed):
            continue
        num = int(m.group(1))
        sub = int(m.group(2)) if m.group(2) else None
        jo_key = _normalize_article_key(num, sub)
        articles.append(jo_key)

        hang, ho, ho_sub = m.group(3), m.group(4), m.group(5)
        if hang or ho:
            detail = ""
            if hang:
                detail += f"제{int(hang)}항"
            if ho:
                detail += f"제{int(ho)}호"
                if ho_sub:
                    detail += f"의{int(ho_sub)}"
            items = detailed.setdefault(jo_key, [])
            if detail not in items:
                items.append(detail)
        else:
            bare.add(jo_key)

    seen = set()
    out = []
    for a in articles:
        if a not in seen:
            seen.add(a)
            out.append(a)

    # bare 로도 등장한 조는 조 전체 대상 → 상세에서 제외
    article_items = {k: v for k, v in detailed.items() if k not in bare}
    return out, article_items


def _extract_tables(text: str) -> list:
    tables = []
    for m in _TABLE_RE.finditer(text):
        num = m.group(1)
        sub = m.group(2)
        key = f"{num}의{sub}" if sub else num
        if key not in tables:
            tables.append(key)
    return tables


def _resolve_effective_date(phrase: str, public_date: str) -> str:
    """단서·본문 텍스트 한 조각에서 시행일자를 결정한다.

    우선순위: 명시 날짜 > 상대 기간 > 공포한 날 > 빈 문자열(미해석)
    """
    m = _EXPLICIT_DATE_RE.search(phrase)
    if m:
        y, mo, d = m.groups()
        try:
            return datetime(int(y), int(mo), int(d)).strftime("%Y%m%d")
        except ValueError:
            pass

    m = _RELATIVE_PERIOD_RE.search(phrase)
    if m and public_date and len(public_date) == 8:
        n = int(m.group(1))
        unit = m.group(2)
        try:
            base = datetime.strptime(public_date, "%Y%m%d")
            if unit == "개월":
                target = base + relativedelta(months=+n)
            elif unit == "년":
                target = base + relativedelta(years=+n)
            else:
                target = base + relativedelta(days=+n)
            return target.strftime("%Y%m%d")
        except ValueError:
            pass

    if _PROMULGATE_DAY_RE.search(phrase):
        return public_date or ""

    return ""


def _split_main_and_exceptions(body: str) -> tuple:
    """부칙 본문을 '다만,' 또는 '단,' 토큰으로 본문/단서절들로 분리한다."""
    parts = re.split(r"(?:다만|단)\s*[,，]\s*", body)
    main = parts[0].strip() if parts else body.strip()
    exceptions = [p.strip() for p in parts[1:] if p.strip()]
    return main, exceptions


def _collect_full_text(addenda: list, public_date: str = "") -> str:
    """해당 공포일과 일치하는 부칙만 골라 한 문자열로 합친다.

    API 가 반환하는 부칙 리스트에는 옛 버전 부칙도 누적 포함되어 있어
    공포일 매칭으로 현재 버전의 부칙만 필터링한다.
    """
    pieces = []
    for bk in addenda or []:
        if public_date and bk.get("부칙공포일자") != public_date:
            continue
        content = (bk.get("부칙내용") or "").strip()
        if content:
            pieces.append(content)
    if not pieces and not public_date:
        for bk in addenda or []:
            content = (bk.get("부칙내용") or "").strip()
            if content:
                pieces.append(content)
    return "\n\n".join(pieces)


def _truncate(text: str, limit: int = _RAW_TEXT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def parse_addenda(addenda: list, public_date: str) -> dict:
    """부칙 리스트와 공포일자를 받아 시행일 분리 정보를 반환한다.

    Args:
        addenda: collect_full_history.py 가 만든 부칙 리스트
                 각 항목 dict 는 "부칙공포일자", "부칙공포번호", "부칙내용" 키를 가진다
        public_date: 해당 법령 버전의 공포일자 (YYYYMMDD)

    Returns:
        dict: {
            "main_effective_date": 본문 시행일 (YYYYMMDD, 추론 실패 시 빈 문자열),
            "exceptions": [{"articles": [...], "article_items": {조키: [상세]},
                            "tables": [...], "effective_date": YYYYMMDD,
                            "raw_phrase": 단서 원문 발췌}, ...],
            "raw_text": 부칙 원문 전체 (1500자 제한)
        }
    """
    raw_text = _collect_full_text(addenda, public_date)

    if not raw_text:
        return {
            "main_effective_date": "",
            "exceptions": [],
            "raw_text": "",
        }

    cut_pattern = (
        r"(?:제\s*[2-9]\d*\s*조\s*[\(\s]|②|③|④|⑤|⑥|⑦|⑧|⑨)"
    )
    m = re.search(rf"^(.*?)(?={cut_pattern})", raw_text, re.DOTALL)
    effective_section = m.group(1).strip() if m else raw_text

    main, ex_phrases = _split_main_and_exceptions(effective_section)
    main_date = _resolve_effective_date(main, public_date)

    exceptions = []
    for phrase in ex_phrases:
        if not phrase:
            continue
        articles, article_items = _extract_article_targets(phrase)
        tables = _extract_tables(phrase)
        if not articles and not tables:
            continue
        eff = _resolve_effective_date(phrase, public_date)
        if not eff:
            continue
        exceptions.append({
            "articles": articles,
            "article_items": article_items,
            "tables": tables,
            "effective_date": eff,
            "raw_phrase": _truncate(phrase, 240),
        })

    return {
        "main_effective_date": main_date,
        "exceptions": exceptions,
        "raw_text": _truncate(raw_text),
    }


if __name__ == "__main__":
    sample = [{
        "부칙공포일자": "20251230",
        "부칙공포번호": "36089",
        "부칙내용": (
            "제1조(시행일) 이 법은 공포한 날부터 시행한다. "
            "다만, 제44조의 개정규정은 공포 후 6개월이 경과한 날부터 시행한다."
        ),
    }]
    import json
    print(json.dumps(parse_addenda(sample, "20251230"),
                     ensure_ascii=False, indent=2))
