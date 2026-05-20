"""
출근길 법령 튜터 — 판례 페어링 알고리즘 (Phase 2 2b-α + 보강)
================================================================
정책 (사용자 결정 2026-05-20):
  - '하루 주제 통일' — 같은 날 조문 카드와 판례 카드를 같은 카테고리로 묶음
  - 일 단위 인접 페어 (월=조문A·화=조문A 관련 판례, 수=조문B·목=조문B 관련 판례, 금=조문C 단독)

알고리즘 (2단계):
  1) ARTICLE_CATEGORY_MAP → 같은 카테고리 후보 풀 (행심·대법원 분리)
  2) ARTICLE_TOPIC_KEYWORDS → 본문(ruling/reasoning/title 등)에 조문 특화 키워드가
     포함된 케이스를 'priority_pool'로 분리. priority_pool 우선 선정, 비어 있으면
     일반 카테고리 풀로 폴백.

source 균형: hash(f'src:{jo}:{date}') % 2 → 행심/대법원 번갈아.
결정론 pick: hash(f'pick:{jo}:{date}') % len(pool).
recent_history (source, case_no) 튜플 set에서 제외.

미매핑 조문(광범위 벌칙 등)은 None 반환 — 호출부에서 판례 카드 생략.
priority_matched 플래그로 정밀 매칭 여부 노출 (디버그/품질 관리).
"""

import ast
import hashlib


# ────────────────────────────────────────────────────────────────
# 매핑 표
# ────────────────────────────────────────────────────────────────

ARTICLE_CATEGORY_MAP = {
    # 음주·약물
    '44': 'drunk',
    '45': 'drunk',
    '50의3': 'drunk',
    '148의2': 'drunk',
    # 무면허
    '43': 'unlicensed',
    '152': 'unlicensed',
    # 사고·뺑소니·공동위험
    '46': 'accident',
    '47': 'accident',
    '54': 'accident',
    '148': 'accident',
    '151': 'accident',
    # 면허·벌점·통고처분
    '93': 'points',
    '163': 'points',
    '164': 'points',
    '165': 'points',
    # 적성검사·면허시험·갱신
    '83': 'aptitude',
    '87': 'aptitude',
    '88': 'aptitude',
    '89': 'aptitude',
}

# 조문 특화 학습 키워드 — 카테고리만으론 학습 가치 보장 안 돼서 본문 키워드까지 본다
# (Codex 권고: 법문 표현 + 판례 표현 같이 넣고, 스캔 대상도 ruling/reasoning뿐 아니라
#  case_name·title·summary 보조 스캔).
ARTICLE_TOPIC_KEYWORDS = {
    '44': ['음주운전', '주취운전', '주취', '혈중알코올', '음주측정'],
    '45': ['약물운전', '과로', '졸음', '운전부적격', '환각'],
    '50의3': ['음주운전 방지장치', '시동잠금', '음주방지장치'],
    '148의2': ['음주', '주취', '음주측정', '재범', '가중처벌'],
    '43': ['무면허', '면허 없이', '면허 정지 중', '면허취소 후 운전'],
    '152': ['무면허', '면허 없이'],
    '46': ['공동위험행위', '공동위험', '공동하여', '집단', '대열', '폭주', '난폭운전', '교통상의 위험'],
    '47': ['위험방지', '일시정지', '경찰관 지시'],
    '54': ['뺑소니', '도주', '구호', '사고 후 미조치', '사고후미조치', '도주차량', '특정범죄가중처벌'],
    '148': ['사고 후 조치', '사고후조치', '도주', '구호의무'],
    '151': ['업무상과실', '치사', '치상', '교통사고처리특례법'],
    '93': ['면허취소', '면허정지', '벌점', '누산점수'],
    '163': ['통고처분', '범칙금'],
    '164': ['통고처분', '범칙금'],
    '165': ['즉결심판', '범칙금 미납'],
    '83': ['운전면허 시험', '면허취득'],
    '87': ['면허 갱신', '면허갱신'],
    '88': ['정기적성검사', '적성검사'],
    '89': ['수시 적성검사', '수시적성검사'],
}

# 대법원 case_name 키워드 → 카테고리 (1차 카테고리 추론용. 우선순위 명시).
CASE_KEYWORD_PRIORITY = [
    'refuse', 'drunk', 'unlicensed', 'accident',
    'points', 'medical', 'commercial', 'aptitude', 'other',
]

CASE_KEYWORDS = {
    'refuse': ['음주측정거부', '측정거부', '음주측정에 응하지'],
    'drunk': ['음주운전', '주취', '약물운전', '음주'],
    'unlicensed': ['무면허'],
    'accident': ['교통사고', '뺑소니', '도주', '사고후미조치', '치사', '치상', '특정범죄가중처벌'],
    'points': ['면허취소', '면허정지', '벌점'],
    'medical': ['신체조건', '의료'],
    'commercial': ['택시', '버스', '운송사업', '운수'],
    'aptitude': ['적성검사'],
    'other': [],
}


# ────────────────────────────────────────────────────────────────
# 카테고리 추론
# ────────────────────────────────────────────────────────────────

def infer_court_case_category(case_name):
    if not case_name:
        return 'other'
    for cat in CASE_KEYWORD_PRIORITY:
        for kw in CASE_KEYWORDS.get(cat, []):
            if kw in case_name:
                return cat
    return 'other'


def categorize_admin_case(case_dict):
    cats = case_dict.get('categories', '[]')
    if isinstance(cats, str):
        try:
            cats = ast.literal_eval(cats)
        except (ValueError, SyntaxError):
            cats = []
    if not cats:
        return 'other'
    for cat in CASE_KEYWORD_PRIORITY:
        if cat in cats:
            return cat
    return cats[0] if cats else 'other'


# ────────────────────────────────────────────────────────────────
# 본문 키워드 스캔 (정밀 매칭)
# ────────────────────────────────────────────────────────────────

def _search_text(case_data, source):
    """조문 특화 키워드 검색 대상 텍스트. 본문 + 메타필드 합쳐서 스캔."""
    if source == 'court':
        return ' '.join([
            str(case_data.get('case_name') or ''),
            str(case_data.get('ruling') or ''),
        ])
    # admin
    return ' '.join([
        str(case_data.get('title') or ''),
        str(case_data.get('summary') or ''),
        str(case_data.get('claim') or ''),
        str(case_data.get('reasoning') or ''),
    ])


def _has_topic_keyword(case_data, source, keywords):
    if not keywords:
        return False
    text = _search_text(case_data, source)
    return any(kw in text for kw in keywords)


# ────────────────────────────────────────────────────────────────
# 결정론 stride
# ────────────────────────────────────────────────────────────────

def _stride_hash(seed, mod):
    if mod <= 0:
        return 0
    digest = hashlib.md5(seed.encode('utf-8')).hexdigest()
    return int(digest, 16) % mod


# ────────────────────────────────────────────────────────────────
# 메인: 페어링 선정
# ────────────────────────────────────────────────────────────────

def select_paired_case(jo, target_date, admin_cases, court_cases, recent_history=None):
    """
    Returns: {
      'source': 'admin'|'court',
      'case_no': ...,
      'category': ...,
      'priority_matched': bool,   # 조문 특화 키워드까지 매칭됐는지 (False면 카테고리만)
      'case_data': ...,
    } 또는 None
    """
    jo_str = str(jo)
    cat = ARTICLE_CATEGORY_MAP.get(jo_str)
    if not cat:
        return None

    recent = set(tuple(x) for x in (recent_history or []))
    date_str = str(target_date)
    topic_keywords = ARTICLE_TOPIC_KEYWORDS.get(jo_str, [])

    # 1) 같은 카테고리 후보 풀 (행심·대법원 분리)
    admin_cat = [
        c for c in admin_cases
        if categorize_admin_case(c) == cat
        and ('admin', c.get('case_no', '')) not in recent
        and c.get('case_no')
    ]
    court_cat = [
        (cid, data) for cid, data in court_cases.items()
        if infer_court_case_category(data.get('case_name', '')) == cat
        and ('court', cid) not in recent
    ]

    # 2) 키워드 우선 풀 분리
    admin_priority = [c for c in admin_cat if _has_topic_keyword(c, 'admin', topic_keywords)]
    court_priority = [t for t in court_cat if _has_topic_keyword(t[1], 'court', topic_keywords)]

    if admin_priority or court_priority:
        # priority pool 사용
        admin_pool, court_pool = admin_priority, court_priority
        priority_matched = True
    elif admin_cat or court_cat:
        # fallback: 일반 카테고리 풀
        admin_pool, court_pool = admin_cat, court_cat
        priority_matched = False
    else:
        return None

    # 3) source 결정 (한쪽이 비면 다른 쪽)
    if not admin_pool:
        src = 'court'
    elif not court_pool:
        src = 'admin'
    else:
        src = ['admin', 'court'][_stride_hash(f'src:{jo_str}:{date_str}', 2)]

    # 4) pick 결정 (해시)
    if src == 'admin':
        pool = sorted(admin_pool, key=lambda c: c.get('case_no', ''))
        idx = _stride_hash(f'pick:{jo_str}:{date_str}', len(pool))
        picked = pool[idx]
        return {
            'source': 'admin',
            'case_no': picked['case_no'],
            'category': cat,
            'priority_matched': priority_matched,
            'case_data': picked,
        }
    else:
        pool = sorted(court_pool, key=lambda x: x[0])
        idx = _stride_hash(f'pick:{jo_str}:{date_str}', len(pool))
        cid, data = pool[idx]
        return {
            'source': 'court',
            'case_no': cid,
            'category': cat,
            'priority_matched': priority_matched,
            'case_data': data,
        }
