"""
출근길 법령 튜터 — 자료 레지스트리 기반 인덱스 빌더 (M2.6 재설계 R1·R2)
=====================================================
sources_config.json의 자료 레지스트리를 읽어 각 자료를 유형별 파서로 처리.
자료를 새 버전으로 교체해도 glob 패턴이 자동 인식 → 코드 수정 없이 갱신 가능.

자료 유형(type):
  law_comment  — 해설집 마크다운 (조문 헤더 단위)
  court_cases  — 대법원·하급심 판례 텍스트 (【N】 블록)
  admin_cases  — 행정심판례 JSON
  topic_doc    — 주제별 실무 문서 (R4에서 구현)

출력 (tutor/data/):
  index_law_comment.json    조문 → 해설 청크
  index_cases.json          조문 → 행정심판례 case_no 리스트
  cases_excerpts.json       case_no → 행정심판례 전문 (피드백: 발췌 한도 제거)
  index_court_cases.json    조문 → 대법원 판례 cid 리스트
  court_cases_data.json     cid → 대법원 판례 전문
  index_articles.json       현행 법령 후보 풀 + 가중치 (행정심판 + 대법원 판례 합산)

갱신 방법:
  1) source_dir 폴더에 새 자료 파일을 넣거나 기존 교체 (파일명이 glob에 맞으면 됨)
  2) py tutor/build_indexes.py 재실행
"""

import argparse
import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / 'data'
CONFIG_PATH = SCRIPT_DIR / 'sources_config.json'
RECENT_REVISIONS_PATH = SCRIPT_DIR.parent / 'alarm' / 'data' / 'recent_revisions.json'

# 해설집 조문 헤더 — '### 제N조(제목)' 형태. 괄호 제목 필수 (본문 속 '제88조 4항' 같은 인용 오인 방지)
# 해설집 조문 헤더 — '제N조(제목)'만 있는 줄. 닫는 괄호 뒤에 본문 텍스트가 이어지면
# 다른 법(한국도로교통공단법·시행령 등)을 인용한 것 → '\s*$'로 순수 헤더만 인식
ARTICLE_HEADER = re.compile(r'^#{0,4}\s*제\s*(\d+)\s*조(?:의\s*(\d+))?\s*\(([^)]+)\)\s*$')
# 판례 본문 내 도로교통법 조문 인용 — '도로교통법' 명시 필수 (다른 법 조문 오매핑 방지)
# "도로교통법 시행령/시행규칙 제N조"는 사이에 '시행'이 끼어 매칭 안 됨 → 법률 조문만 추출
ARTICLE_CITATION = re.compile(r'「?\s*도로교통법\s*」?\s*제\s*(\d+)\s*조(?:의\s*(\d+))?')

COMMENT_CONTENT_MAX = 6000

# 2005.5.31 도로교통법 전부개정(법률 제7545호) 시행일 — 조문 번호가 전면 재편된 기준점.
# 이 날짜 이전 선고 판례의 "제N조"는 옛 번호 체계 → 현행 조문에 숫자로 매핑하면 오류
# (예: 옛 제40조=무면허, 현행 제40조=정비불량차).
RENUMBER_DATE = (2006, 6, 1)


def parse_ymd(s):
    """'2023.06.29' · '2004. 12. 10' 등 날짜 문자열 → (년, 월, 일) 튜플. 실패 시 None."""
    if not s:
        return None
    m = re.search(r'(\d{4})\D{1,3}(\d{1,2})\D{1,3}(\d{1,2})', str(s))
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def is_pre_renumber(ymd):
    """전부개정 시행일(2006-06-01) 이전이면 True — 옛 조문번호 체계."""
    return ymd is not None and ymd < RENUMBER_DATE


# 대법원 판례 사건명 죄명 → 도로교통법 조문 매핑
CHARGE_TO_ARTICLE = {
    '음주운전': '44',
    '무면허운전': '43',
    '측정거부': '44',
    '사고후미조치': '54',
    '사고후미신고': '54',
    '약물운전': '45',
    '난폭운전': '46의3',
    '공동위험행위': '46',
}

# 조문 → 카테고리 매핑
ARTICLE_CATEGORY = {
    '5': '신호위반', '17': '제한속도', '25': '교차로통행', '27': '보행자보호',
    '32': '주정차', '43': '무면허·결격기간', '44': '음주운전', '45': '약물·질병',
    '46': '난폭운전', '46의3': '난폭운전', '47': '음주측정거부',
    '50': '운전자의무', '51': '운전자의무', '52': '운전자의무', '53': '운전자의무',
    '54': '교통사고', '80': '면허일반', '82': '무면허·결격기간', '83': '면허취득',
    '84': '면허시험', '85': '면허종류', '87': '적성검사·갱신', '88': '적성검사·갱신',
    '89': '벌점', '90': '면허취소·정지', '91': '면허취소·정지', '92': '면허취소·정지',
    '93': '면허취소·정지', '94': '벌점', '95': '면허재취득',
    '148의2': '음주운전', '110': '사업용면허',
}

# 카테고리별 학습 가치 우선순위 (0~1)
CATEGORY_PRIORITY = {
    '음주운전': 1.0, '음주측정거부': 0.95, '약물·질병': 0.95, '교통사고': 0.9,
    '면허취소·정지': 0.85, '무면허·결격기간': 0.8, '난폭운전': 0.8,
    '운전자의무': 0.75, '벌점': 0.7, '보행자보호': 0.7, '제한속도': 0.65,
    '신호위반': 0.6, '교차로통행': 0.6, '적성검사·갱신': 0.55, '면허시험': 0.5,
    '면허재취득': 0.5, '면허취득': 0.4, '면허종류': 0.4, '면허일반': 0.4,
    '사업용면허': 0.4, '주정차': 0.4,
}
DEFAULT_CATEGORY_PRIORITY = 0.3

# topic_doc 청크 최대 길이 (헤더 분할 후 큰 섹션은 이 크기로 재분할)
TOPIC_CHUNK_MAX = 3000

# 주제 키워드 → 카테고리 (topic_doc 청크를 조문 카테고리에 연결)
TOPIC_KEYWORDS = {
    '음주운전': ['음주운전', '음주측정', '혈중알코올', '주취운전'],
    '음주측정거부': ['측정거부', '측정 거부'],
    '무면허·결격기간': ['무면허', '면허 결격', '결격기간'],
    '교통사고': ['교통사고', '뺑소니', '도주차량', '도주치', '미조치', '치상', '치사', '사고후'],
    '신호위반': ['신호위반', '신호 위반'],
    '제한속도': ['속도위반', '과속'],
    '보행자보호': ['횡단보도', '보행자보호'],
    '난폭운전': ['난폭운전', '보복운전', '공동위험'],
    '약물·질병': ['약물운전', '마약', '향정'],
    '면허취소·정지': ['면허취소', '면허정지', '운전면허 취소'],
    '중앙선': ['중앙선'],
    '어린이보호': ['어린이보호구역', '통학버스', '민식이법', '스쿨존'],
}


def jo_key(main, sub):
    return f"{main}의{sub}" if sub else main


# 다른 법령 경계 — '법령명 + 제N조' 조합만 경계로 인정 (R15-1a, Codex 반영).
# '헌법 제12조'는 경계가 되지만 '방법'·'위법' 같은 일반어 단독은 경계가 아니다.
# 2글자 법령명('헌'이 1글자) + 공백 든 법률명(교통사고처리 특례법 등)은 명시한다 —
# '[가-힣]{2,20}법'이 못 잡아 그 뒤 조문이 도로교통법 조문으로 오인되던 버그.
_OTHER_LAW = re.compile(
    r'(헌법|형법|민법|상법|세법'
    r'|교통사고처리\s*특례법'
    r'|특정범죄\s*가중처벌\s*등에\s*관한\s*법률'
    r'|자동차관리법'
    r'|[가-힣]{2,20}법(?:률)?)\s*제\s*\d+\s*조')
_JO_PAT = re.compile(r'제\s*(\d+)\s*조(?:의\s*(\d+))?')
_ROAD_LAW_MARKER = re.compile(r'「?\s*도로교통법\s*」?(?!\s*시행)')
# 조문 범위 표기 — '제N조부터 제M조까지', '제N조~제M조', '제N조 내지 제M조'.
# 범위는 조문군을 분류·언급한 것이지 그 조문을 주제로 다룬 게 아니다 (R14-1a).
# 양끝이 모두 '조'여야 매칭 — '제N조제1항부터 제3항까지'(항 범위)는 걸리지 않는다.
_RANGE_PAT = re.compile(
    r'제\s*(\d+)\s*조(?:의\s*(\d+))?\s*(?:부터|~|∼|내지)\s*제\s*(\d+)\s*조(?:의\s*(\d+))?\s*(?:까지)?')


def extract_road_law_articles(text):
    """텍스트 → (direct, ranged) 도로교통법(법률) 조문번호 집합.

    direct: '제N조'로 직접·단독 인용된 조문.
    ranged: '제N조부터 제M조까지' 등 범위 표기에만 등장한 조문(양끝).
    범위·직접에 모두 나오면 direct 우선. 판례 매핑은 둘을 합쳐 쓰고(기존 동작
    유지), topic_doc 선정만 direct/ranged를 구분해 가중치를 달리한다 (R14-1).

    '도로교통법' 마커 뒤 최대 200자 구간(다른 법령명 등장 전까지)에서 수집한다.
    시행령·시행규칙 조문은 마커의 negative lookahead로 제외된다.
    """
    direct, ranged = set(), set()
    for m in _ROAD_LAW_MARKER.finditer(text):
        # "구 도로교통법"(옛 법 인용) 구간은 제외 — 옛 조문번호가 현행에 오매핑되는 것 차단.
        # 한국 판결문은 폐지·개정 전 법을 인용할 때 반드시 "구 "를 붙이는 관례를 따른다.
        prev = text[max(0, m.start() - 3):m.start()].replace('「', '').strip()
        if prev.endswith('구'):
            continue
        seg = text[m.end():m.end() + 200]
        cut = len(seg)
        # '시행령'·'시행규칙' 등장 → 그 이후 '제N조'는 하위법령 조문이므로 제외
        # (행정심판 결정문은 "도로교통법 제93조 ... 같은 법 시행규칙 제84조" 식으로
        #  법률·하위법령 조문을 이어 나열 — 시행규칙 조문이 법률 조문으로 오매핑되는 것 차단)
        sub = re.search(r'시행\s*(?:령|규칙)', seg)
        if sub:
            cut = min(cut, sub.start())
        # 다른 법령 조문이 나오면 그 앞까지만 ('법령명 + 제N조' 조합, 도로교통법 제외)
        for lm in _OTHER_LAW.finditer(seg):
            if lm.group(1) != '도로교통법':
                cut = min(cut, lm.start())
                break
        body = seg[:cut]
        # 범위 표기 — 양끝 조문을 ranged에 넣고, 그 구간을 공백 마스킹해
        # 직접 인용 수집(_JO_PAT)에서 제외한다. 가지번호(조의N)를 보존하고
        # direct와 동일한 구법 문맥 검사를 거친다 (Codex 코드검증 반영).
        for rm in _RANGE_PAT.finditer(body):
            rctx = body[max(0, rm.start() - 80):rm.end() + 45]
            if re.search(r'개정되기\s*전|전부\s*개정|전문\s*개정|현행\s*제\s*\d+\s*조', rctx):
                continue
            ranged.add(jo_key(rm.group(1), rm.group(2)))
            ranged.add(jo_key(rm.group(3), rm.group(4)))
        body = _RANGE_PAT.sub(lambda mm: ' ' * (mm.end() - mm.start()), body)
        for jm in _JO_PAT.finditer(body):
            # 이 '제N조' 인용 주변에 구법 표기가 있으면 옛 조문번호 → 제외 (R7-1 보강).
            # 판결문은 옛 법을 '...개정되기 전의 것) 제N조', '제N조(현행 제M조 참조)'
            # 처럼 표기한다 — "구 " 접두어 없이 괄호·참조구로만 표시하는 경우 대응.
            ctx = body[max(0, jm.start() - 80):jm.end() + 45]
            if re.search(r'개정되기\s*전|전부\s*개정|전문\s*개정|현행\s*제\s*\d+\s*조', ctx):
                continue
            direct.add(jo_key(jm.group(1), jm.group(2)))
    ranged -= direct
    return direct, ranged


# ─── 파서: 해설집 (law_comment) ──────────────────────────────────

def clean_comment_text(text):
    """해설집 텍스트 경량 정제 — 마크다운 표 + PDF 변환 잔재 제거 (R8 C2).
    PDF→마크다운 변환 손상은 완전 복원 불가 — 규칙형 정제로 가독성만 높인다."""
    text = re.sub(r'<br\s*/?>', '\n', text)               # <br> 태그 → 줄바꿈
    out = []
    for line in text.split('\n'):
        s = line.strip()
        if not s:
            out.append('')
            continue
        if s.isdigit():                                   # 페이지 번호 등 숫자만 있는 줄 제거
            continue
        # 표 구분선(|---|---|, | :--- | ---: |) 제거
        if '|' in s and s.count('-') >= 3 and re.fullmatch(r'[\s:\-|]+', s):
            continue
        # 표 데이터 행(| A | B | C |) → ' · ' 구분 평문
        if s.startswith('|') and s.endswith('|') and s.count('|') >= 3:
            cells = [c.strip() for c in s.strip('|').split('|')]
            line = ' · '.join(c for c in cells if c)
        # 표 잔재 — 파이프·공백뿐인 줄 제거, 줄 앞뒤 외톨이 파이프('과와 | | |', '| 관') 정리
        if re.fullmatch(r'[\s|]+', s):
            continue
        line = re.sub(r'^\s*\|[\s|]*', '', line)
        line = re.sub(r'\s*\|[\s|]*$', '', line)
        # 흩어진 가운뎃점 잔재(" · ･ ") 정리 — 2개 이상 연속만 (단일 '·'는 보존)
        line = re.sub(r'[·･]\s*(?:[·･]\s*)+', '·', line)
        if line.strip():
            out.append(line)
        else:
            out.append('')
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(out))


# 문장 끝 — 한글/영문 한 글자 + 마침표류 + (선택)닫는 따옴표 + 공백/끝.
# 숫자 뒤 마침표('4.5'·목록 '1.')는 글자 조건으로 자연히 제외 (R13-D 피드백 6).
_SENT_END = re.compile(r'[가-힣A-Za-z][.?!。．][)\]」』”’]?(?=\s|$)')


def clip_at_sentence(text, limit):
    """해설집 청크를 한도 이내 마지막 '문장 끝'에서 매듭 — 중간에서 잘리는 것 방지.
    문장 끝을 못 찾으면 줄바꿈·공백 순으로 자르고 말줄임표로 절단을 표시한다."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    ends = list(_SENT_END.finditer(head))
    if ends:
        return head[:ends[-1].end()].rstrip()
    # fallback — 문장 끝이 없으면 마지막 줄바꿈/공백에서 자르고 절단 표시
    nl, sp = head.rfind('\n'), head.rfind(' ')
    cut = nl if nl > limit * 0.5 else (sp if sp > limit * 0.5 else limit)
    return head[:cut].rstrip() + ' …'


def parse_law_comment(path):
    """해설집 마크다운 → 조문번호별 청크. '### 제N조' 헤더도 인식."""
    text = path.read_text(encoding='utf-8')
    lines = text.split('\n')

    headers = []  # [(line_idx, jo_key, title)]
    for i, line in enumerate(lines):
        m = ARTICLE_HEADER.match(line.strip())
        if m:
            headers.append((i, jo_key(m.group(1), m.group(2)), m.group(3) or ''))

    candidates = defaultdict(list)
    for idx, (li, jo, title) in enumerate(headers):
        end = headers[idx + 1][0] if idx + 1 < len(headers) else len(lines)
        chunk = '\n'.join(lines[li:end]).strip()
        if chunk:
            candidates[jo].append((title, chunk))

    index = {}
    for jo, chunks in candidates.items():
        title, content = max(chunks, key=lambda c: len(c[1]))
        index[jo] = {
            'title': title.strip(),
            'content': clip_at_sentence(clean_comment_text(content), COMMENT_CONTENT_MAX),
            'occurrences': len(chunks),
        }
    return index


# ─── 파서: 행정심판례 (admin_cases) ──────────────────────────────────

# 행정심판 결정문 전처리 — 끝의 '참조 조문' 부록 제거 (R8 B4)
_REF_APPENDIX = re.compile(r'참조\s*조문')


def cut_reference_appendix(text):
    """결정문 끝 '참조 조문' 부록 제거 — 가독성 + 색인 정확도(부록의 나열 조문 제외)."""
    m = _REF_APPENDIX.search(text)
    if m and m.start() > len(text) * 0.5:
        return text[:m.start()].rstrip()
    return text


def parse_admin_cases(path):
    """행정심판례 JSON → 조문 매핑 + 전문 발췌 (한도 제거)."""
    cases = json.loads(path.read_text(encoding='utf-8'))
    index = defaultdict(list)
    excerpts = {}
    pre_count = 0

    for case in cases:
        case_no = case.get('case_no')
        if not case_no:
            continue
        # B4: 끝의 '참조 조문' 부록 제거 — 표시·색인 모두 적용
        reasoning = cut_reference_appendix(case.get('reasoning', ''))

        # 전부개정(2006.6.1) 이전 행정심판례는 "제N조"가 옛 번호 체계 →
        # 죄명 키워드 대체 수단이 없어 숫자 매핑 자체를 제외
        if is_pre_renumber(parse_ymd(case.get('date'))):
            pre_count += 1
            continue
        _direct, _ranged = extract_road_law_articles(reasoning)
        article_set = _direct | _ranged   # 판례 매핑은 직접+범위 합산 (기존 동작 유지)
        if not article_set:
            continue

        for jo in article_set:
            index[jo].append(case_no)

        excerpts[case_no] = {
            'title': case.get('title', ''),
            'date': case.get('date', ''),
            'court': case.get('court', ''),
            'result': case.get('result', ''),
            'year': case.get('year', ''),
            'summary': case.get('summary', '')[:300],
            'reasoning': reasoning,  # 표시용 — 참조조문 부록만 제거(B4), 관계법령 절은 보존
        }

    if pre_count:
        print(f"   ⚖️ 구법(전부개정 이전) 행정심판례 {pre_count}건 — 숫자 매핑 제외")
    return {jo: sorted(set(v)) for jo, v in index.items()}, excerpts


# ─── 파서: 대법원·하급심 판례 (court_cases) ──────────────────────────────────

_REF_MARKER = re.compile(r'[\[【]\s*참조\s*조문\s*[\]】]')


def cut_court_appendix(ruling):
    """대법원 판례 색인용 — [참조조문] 부록 이후를 제거 (R15-1b, Codex 반영).
    [참조조문]은 판결 이유가 아니라 여러 법령 조문을 압축 나열한 메타데이터라
    조문 매핑을 오염시킨다(타법 조문이 도로교통법 조문으로 오인). [참조조문] 뒤에
    [판시사항]/[판결요지]가 또 나오면 한 블록에 여러 판례가 뭉친 데이터인데, 그
    경우에도 [참조조문] 앞(첫 판례 본문)까지만 색인해 뒤 판례 오염을 막고 mixed로
    알린다. 마커는 [참조 조문]·【참조조문】 등 표기 변형을 허용한다."""
    m = _REF_MARKER.search(ruling)
    if not m:
        return ruling, False
    pos = m.start()
    mixed = '[판시사항]' in ruling[pos:] or '[판결요지]' in ruling[pos:]
    return ruling[:pos].rstrip(), mixed


def parse_court_cases(path):
    """판례 통합 텍스트 → 【N】 블록 파싱. 죄명·판결요지로 조문 매핑."""
    text = path.read_text(encoding='utf-8')
    blocks = re.split(r'━{5,}', text)

    index = defaultdict(list)
    data = {}
    pre_count = 0
    mixed_count = 0

    for block in blocks:
        block = block.strip()
        m = re.search(r'【(\d+)】\s*(.+)', block)
        if not m:
            continue
        num, case_name = m.group(1), m.group(2).strip()

        m_date = re.search(r'선고일\s*:\s*([\d.]+)\s*\|\s*(.+)', block)
        m_caseno = re.search(r'사건번호\s*:\s*(\S+)', block)
        m_ruling = re.search(r'\[판결요지\]\s*(.+)', block, re.DOTALL)
        if not m_caseno:
            continue

        case_no = m_caseno.group(1).strip()
        cid = case_no if case_no not in data else f"{case_no}#{num}"
        ruling = m_ruling.group(1).strip() if m_ruling else ''
        ruling = re.sub(r'<br\s*/?>', '\n', ruling).strip()

        data[cid] = {
            'case_name': case_name,
            'date': m_date.group(1).strip() if m_date else '',
            'court': m_date.group(2).strip() if m_date else '',
            'case_no': case_no,
            'ruling': ruling,
        }

        articles = set()
        for charge, jo in CHARGE_TO_ARTICLE.items():
            if charge in case_name:
                articles.add(jo)
        # 전부개정(2006.6.1) 이전 선고 판례는 "제N조"가 옛 번호 체계 →
        # 숫자 추출 제외, 번호 재편과 무관한 죄명 키워드 매핑만 사용
        if is_pre_renumber(parse_ymd(data[cid]['date'])):
            pre_count += 1
        else:
            idx_ruling, mixed = cut_court_appendix(ruling)
            if mixed:
                mixed_count += 1
            _direct, _ranged = extract_road_law_articles(idx_ruling)
            articles |= _direct | _ranged   # 판례 매핑은 직접+범위 합산
        for jo in articles:
            index[jo].append(cid)

    if pre_count:
        print(f"   ⚖️ 구법(전부개정 이전 선고) 판례 {pre_count}건 — 죄명 키워드만 매핑")
    if mixed_count:
        print(f"   ⚠️ [참조조문] 뒤 본문 마커 재출현 {mixed_count}건 — 여러 판례 뭉침, cut 보류")
    return {jo: sorted(set(v)) for jo, v in index.items()}, data


# ─── 파서: 주제별 실무 문서 (topic_doc) ──────────────────────────────────

def extract_topic_keywords(text):
    """텍스트에서 카테고리 키워드 추출 (조문 카테고리 연결용)."""
    found = []
    for cat, kws in TOPIC_KEYWORDS.items():
        if any(kw in text for kw in kws):
            found.append(cat)
    return found


def parse_topic_doc(path, doc_id):
    """주제별 실무 문서 → 청크 리스트.

    1차: 마크다운 헤더(#~####)로 섹션 분할.
    2차: 큰 섹션(TOPIC_CHUNK_MAX 초과)은 크기 기준 재분할
         (헤더가 거의 없는 문서 — 사고조사판례집 — 대응).
    각 청크: doc_id, chunk_id, title, content, articles(조문 인용), keywords(카테고리)
    """
    text = path.read_text(encoding='utf-8')
    lines = text.split('\n')

    sections = []
    cur_title, cur = doc_id, []
    header_pat = re.compile(r'^#{1,4}\s+(.+)')
    for line in lines:
        h = header_pat.match(line)
        if h and len(h.group(1).strip()) > 2:
            if cur:
                sections.append((cur_title, '\n'.join(cur).strip()))
            cur_title = h.group(1).strip()
            cur = [line]
        else:
            cur.append(line)
    if cur:
        sections.append((cur_title, '\n'.join(cur).strip()))

    chunks = []
    for title, content in sections:
        if len(content) < 80:
            continue
        if len(content) <= TOPIC_CHUNK_MAX:
            chunks.append((title, content))
        else:
            for i in range(0, len(content), TOPIC_CHUNK_MAX):
                part = content[i:i + TOPIC_CHUNK_MAX]
                suffix = f" ({i // TOPIC_CHUNK_MAX + 1})" if i > 0 else ""
                chunks.append((title + suffix, part))

    result = []
    for idx, (title, content) in enumerate(chunks):
        content = clean_comment_text(content)  # R9-4: 수사실무 등 PDF 변환 잔재 정제
        direct, ranged = extract_road_law_articles(content)
        result.append({
            'doc_id': doc_id,
            'chunk_id': f"{doc_id}-{idx + 1}",
            'title': title,
            'content': content,
            'articles': sorted(direct),         # 직접·단독 인용 조문 (R14-1)
            'range_articles': sorted(ranged),   # 범위 표기로만 등장한 조문
            'keywords': extract_topic_keywords(title + '\n' + content),
        })
    return result


# ─── 현행 법령 풀 인덱스 ──────────────────────────────────

def load_recent_revised(path):
    """recent_revisions.json에서 최근 개정된 매핑법률조문 집합."""
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding='utf-8'))
    recent = set()
    for v in data.get('버전들', []):
        for art in v.get('변경조문', []):
            mapped = art.get('매핑법률조문')
            if mapped:
                recent.add(mapped)
    return recent


def compute_weight(admin_count, court_count, categories, has_comment, has_recent, max_total):
    """학습 가치 가중치 (0~1). 행정심판 + 대법원 판례 수 합산.

    후보 풀은 이미 '해설집 보유' 게이트를 통과한 조문만 → comment_bonus는
    풀 안에서 항상 1.0(상수)이라 순위에 영향 없음. 점수는 case/category/recent로만 산출.
    """
    total = admin_count + court_count
    case_score = math.log(total + 1) / math.log(max_total + 1) if max_total > 0 else 0.0
    if categories:
        cat_score = max(CATEGORY_PRIORITY.get(c, DEFAULT_CATEGORY_PRIORITY) for c in categories)
    else:
        cat_score = DEFAULT_CATEGORY_PRIORITY
    recent_score = 1.0 if has_recent else 0.0
    comment_bonus = 1.0 if has_comment else 0.0
    score = 0.45 * case_score + 0.35 * cat_score + 0.20 * recent_score
    return {
        'case_score': round(case_score, 3),
        'category_score': round(cat_score, 3),
        'recent_score': round(recent_score, 3),
        'comment_bonus': round(comment_bonus, 3),
        'total': round(score, 3),
    }


def build_article_index(law_index, cases_index, court_index, recent_revised, law_articles_index):
    """현행 법령 후보 조문 풀 (R12-A + Phase 1 다중자료원 OR).

    통과 조건 (OR):
      1) 충실한 해설집(800자 이상) — 기존 R12-A. 해설집만으로 카드 완결.
      2) 법령 원문 보유 + 판례 1건 이상 — Phase 1 신규. 해설집이
         일부 벌칙 조문(제148의2 음주가중·제152 무면허처벌 등)을
         다루지 않아 누락되던 강의 핵심 조문 복구.
    판례 수는 게이트 후 가중치(weight_score)에 반영된다.
    """
    MIN_COMMENT = 800
    MIN_CASE_FALLBACK = 1
    all_jo = set(law_index) | set(cases_index) | set(court_index) | set(law_articles_index)

    def passes_gate(jo):
        if len((law_index.get(jo) or {}).get('content', '')) >= MIN_COMMENT:
            return True
        if jo in law_articles_index:
            case_total = len(cases_index.get(jo, [])) + len(court_index.get(jo, []))
            if case_total >= MIN_CASE_FALLBACK:
                return True
        return False

    pool_jo = sorted(jo for jo in all_jo if passes_gate(jo))
    n_full = sum(1 for j in pool_jo if len((law_index.get(j) or {}).get('content', '')) >= MIN_COMMENT)
    n_fallback = len(pool_jo) - n_full
    print(f"   게이트: 전체 {len(all_jo)}개 → 후보 {len(pool_jo)}개"
          f" (해설집 통과 {n_full} + 자료 폴백 {n_fallback})")
    max_total = max(
        (len(cases_index.get(j, [])) + len(court_index.get(j, [])) for j in pool_jo),
        default=1,
    )
    result = {}
    for jo in pool_jo:
        ac = len(cases_index.get(jo, []))
        cc = len(court_index.get(jo, []))
        cat = ARTICLE_CATEGORY.get(jo)
        cats = [cat] if cat else []
        has_comment = jo in law_index
        has_recent = jo in recent_revised
        bd = compute_weight(ac, cc, cats, has_comment, has_recent, max_total)
        result[jo] = {
            'admin_case_count': ac,
            'court_case_count': cc,
            'categories': cats,
            'has_comment': has_comment,
            'has_recent_revision': has_recent,
            'weight_score': bd['total'],
            'score_breakdown': bd,
        }
    return result


# ─── 현행 조문 원문 + 연혁 (R9-3) ──────────────────────────────────

def _article_full_text(jo_data):
    """조문 dict → 조문내용 + 항/호 합친 전문."""
    parts = [(jo_data.get('조문내용') or '').strip()]
    for hang in jo_data.get('항', []) or []:
        ht = (hang.get('항내용') or '').strip()
        if ht:
            parts.append(ht)
        for ho in hang.get('호', []) or []:
            hot = (ho.get('호내용') or '').strip()
            if hot:
                parts.append('  ' + hot)
    return '\n'.join(p for p in parts if p)


def build_law_article_indexes(history_path):
    """article_history.json → (현행 조문 원문, 조문별 실질 개정 시행일).
    조문변경여부 메타데이터는 거짓양성이 많아 신뢰 불가 → 버전 간 조문 전문 텍스트를
    직접 비교해 '실질 변경'만 연혁으로 인정한다 (Codex 설계검증 지적)."""
    if not history_path or not Path(history_path).exists():
        print(f"   ⚠️ article_history.json 없음 ({history_path}) — 조문원문·연혁 미생성")
        return {}, {}
    try:
        data = json.loads(Path(history_path).read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError) as e:
        print(f"   ⚠️ article_history.json 읽기 실패 ({type(e).__name__})")
        return {}, {}
    today = datetime.now().strftime('%Y%m%d')
    versions = data.get('법령', {}).get('법률', {}).get('버전', [])
    # 시행일자 있고 이미 시행된 버전만 (미래 시행본 제외 — 현행 기준), 시행일 오름차순
    versions = sorted((v for v in versions if v.get('시행일자') and v['시행일자'] <= today),
                      key=lambda v: v['시행일자'])
    if not versions:
        print("   ⚠️ 시행된 버전 없음 — 조문원문·연혁 미생성")
        return {}, {}
    history, prev = {}, {}
    for v in versions:
        for key, jo in (v.get('조문') or {}).items():
            text = _article_full_text(jo)
            if not text:
                continue
            if key in prev and text != prev[key]:
                history.setdefault(key, []).append(
                    {'시행일자': v.get('시행일자', ''), '공포일자': v.get('공포일자', '')})
            prev[key] = text
    # 현행 조문 원문 = 최신(이미 시행된 마지막) 버전의 조문만 — 폐지·삭제 조문 잔류 방지
    articles = {}
    for key, jo in (versions[-1].get('조문') or {}).items():
        text = _article_full_text(jo)
        if text:
            articles[key] = text
    return articles, history


def resolve_article_history_path(arg_value):
    """article_history.json 경로 — 인자 > 환경변수 > 메인 프로젝트 기본 경로."""
    if arg_value:
        return arg_value
    env = os.environ.get('ARTICLE_HISTORY_PATH')
    if env:
        return env
    return str(SCRIPT_DIR.parent.parent / '도로교통법-한눈에' / 'data' / 'article_history.json')


# ─── 메인 ──────────────────────────────────

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='자료 레지스트리 기반 인덱스 빌더 (M2.6)')
    parser.add_argument('--config', type=str, default=str(CONFIG_PATH))
    parser.add_argument('--article-history', type=str, default=None,
                        help='article_history.json 경로 (미지정 시 환경변수·기본 경로)')
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    source_dir = Path(config['source_dir'])

    print("=" * 60)
    print("  📚 인덱스 빌더 — 자료 레지스트리 기반 (M2.6 R1·R2)")
    print("=" * 60)
    if not source_dir.exists():
        print(f"❌ 자료 폴더 없음: {source_dir}")
        sys.exit(1)
    print(f"📁 자료 폴더: {source_dir}\n")

    law_index = {}
    cases_index, cases_excerpts = {}, {}
    court_index, court_data = {}, {}
    topic_chunks = []

    for src in config['sources']:
        if not src.get('enabled', True):
            print(f"⏭️ {src['id']} (비활성 — config에서 enabled=true 시 활성화)")
            continue
        matches = sorted(source_dir.glob(src['glob']))
        if not matches:
            print(f"⚠️ {src['id']}: 매칭 파일 없음 (glob: {src['glob']})")
            continue
        path = matches[-1]  # 이름순 최신
        print(f"📄 {src['id']} [{src['type']}]: {path.name}")

        if src['type'] == 'law_comment':
            law_index = parse_law_comment(path)
            print(f"   ✅ 조문 청크 {len(law_index)}개")
        elif src['type'] == 'admin_cases':
            cases_index, cases_excerpts = parse_admin_cases(path)
            print(f"   ✅ 조문 매핑 {len(cases_index)}개 · 발췌 {len(cases_excerpts)}건")
        elif src['type'] == 'court_cases':
            court_index, court_data = parse_court_cases(path)
            print(f"   ✅ 조문 매핑 {len(court_index)}개 · 판례 {len(court_data)}건")
        elif src['type'] == 'topic_doc':
            chunks = parse_topic_doc(path, src['id'])
            topic_chunks.extend(chunks)
            with_article = sum(1 for c in chunks if c['articles'])
            print(f"   ✅ 주제 청크 {len(chunks)}개 (조문 인용 포함 {with_article}개)")
        else:
            print(f"   ⚠️ 알 수 없는 type: {src['type']}")

    print("\n📄 현행 조문 원문 + 연혁 (article_history.json)...")
    law_articles, law_history = build_law_article_indexes(
        resolve_article_history_path(args.article_history))
    if law_articles:
        print(f"   ✅ 현행 조문 {len(law_articles)}개 · 연혁 보유 {len(law_history)}개")

    recent_revised = load_recent_revised(RECENT_REVISIONS_PATH)
    article_index = build_article_index(law_index, cases_index, court_index, recent_revised, law_articles)

    print(f"\n📊 현행 법령 후보 풀: {len(article_index)}개 조문")
    top10 = sorted(article_index.items(), key=lambda kv: -kv[1]['weight_score'])[:10]
    for jo, info in top10:
        cats = ','.join(info['categories']) or '-'
        print(f"   제{jo:>5s}조 — w={info['weight_score']:.3f} | "
              f"행정심판 {info['admin_case_count']:>4d} + 대법원 {info['court_case_count']:>3d} | {cats}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().isoformat()
    outputs = [
        ('index_law_comment.json', {'생성일시': ts, '설명': '조문 → 해설 청크', '조문수': len(law_index), '조문별': law_index}),
        ('index_cases.json', {'생성일시': ts, '설명': '조문 → 행정심판례 case_no', '조문수': len(cases_index), '조문별': cases_index}),
        ('cases_excerpts.json', {'생성일시': ts, '설명': 'case_no → 행정심판례 전문', '발췌수': len(cases_excerpts), '데이터': cases_excerpts}),
        ('index_court_cases.json', {'생성일시': ts, '설명': '조문 → 대법원·하급심 판례 cid', '조문수': len(court_index), '조문별': court_index}),
        ('court_cases_data.json', {'생성일시': ts, '설명': 'cid → 대법원·하급심 판례 전문', '판례수': len(court_data), '데이터': court_data}),
        ('index_articles.json', {'생성일시': ts, '설명': '현행 법령 후보 풀 + 가중치', '조문수': len(article_index), '조문별': article_index}),
        ('index_topic_docs.json', {'생성일시': ts, '설명': '주제별 실무 문서 청크 (수사실무·사고판례집)', '청크수': len(topic_chunks), '청크': topic_chunks}),
        ('index_law_articles.json', {'생성일시': ts, '설명': '현행 도로교통법 조문 원문', '조문수': len(law_articles), '조문별': law_articles}),
        ('index_law_history.json', {'생성일시': ts, '설명': '조문별 실질 개정 시행일 (연혁 주의 판정용)', '조문수': len(law_history), '조문별': law_history}),
    ]

    print("\n💾 저장:")
    for fn, payload in outputs:
        p = OUTPUT_DIR / fn
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        sz = p.stat().st_size / 1024
        s = f"{sz:.0f} KB" if sz < 1024 else f"{sz / 1024:.1f} MB"
        print(f"   {fn}  ({s})")


if __name__ == '__main__':
    main()
