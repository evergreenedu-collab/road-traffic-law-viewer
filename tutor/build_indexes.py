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
ARTICLE_HEADER = re.compile(r'^#{0,4}\s*제\s*(\d+)\s*조(?:의\s*(\d+))?\s*\(([^)]+)\)')
# 판례 본문 내 도로교통법 조문 인용 — '도로교통법' 명시 필수 (다른 법 조문 오매핑 방지)
# "도로교통법 시행령/시행규칙 제N조"는 사이에 '시행'이 끼어 매칭 안 됨 → 법률 조문만 추출
ARTICLE_CITATION = re.compile(r'「?\s*도로교통법\s*」?\s*제\s*(\d+)\s*조(?:의\s*(\d+))?')

COMMENT_CONTENT_MAX = 4000

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


_OTHER_LAW = re.compile(r'[가-힣]{2,10}법(?:률)?')
_JO_PAT = re.compile(r'제\s*(\d+)\s*조(?:의\s*(\d+))?')
_ROAD_LAW_MARKER = re.compile(r'「?\s*도로교통법\s*」?(?!\s*시행)')


def extract_road_law_articles(text):
    """텍스트에서 도로교통법(법률) 조문번호만 추출.

    '도로교통법' 마커 뒤 최대 200자 구간(다른 법령명 등장 전까지)에서
    '제N조'를 수집한다. 결정문이 법 이름을 한 번 쓰고 조문을 나열하는
    패턴('「도로교통법」 제2조, 제44조, 제82조')에 대응.
    시행령·시행규칙 조문은 마커의 negative lookahead로 제외된다.
    """
    result = set()
    for m in _ROAD_LAW_MARKER.finditer(text):
        seg = text[m.end():m.end() + 200]
        # 다른 법령명이 나오면 그 앞까지만 (도로교통법 자신은 경계 아님)
        cut = len(seg)
        for lm in _OTHER_LAW.finditer(seg):
            if not seg[lm.start():lm.end()].endswith('도로교통법'):
                cut = lm.start()
                break
        for jm in _JO_PAT.finditer(seg[:cut]):
            result.add(jo_key(jm.group(1), jm.group(2)))
    return result


# ─── 파서: 해설집 (law_comment) ──────────────────────────────────

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
            'content': content[:COMMENT_CONTENT_MAX],
            'occurrences': len(chunks),
        }
    return index


# ─── 파서: 행정심판례 (admin_cases) ──────────────────────────────────

def parse_admin_cases(path):
    """행정심판례 JSON → 조문 매핑 + 전문 발췌 (한도 제거)."""
    cases = json.loads(path.read_text(encoding='utf-8'))
    index = defaultdict(list)
    excerpts = {}

    for case in cases:
        case_no = case.get('case_no')
        if not case_no:
            continue
        reasoning = case.get('reasoning', '')

        article_set = extract_road_law_articles(reasoning)
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
            'reasoning': reasoning,  # 전문 (피드백 ①: 생략 없음)
        }

    return {jo: sorted(set(v)) for jo, v in index.items()}, excerpts


# ─── 파서: 대법원·하급심 판례 (court_cases) ──────────────────────────────────

def parse_court_cases(path):
    """판례 통합 텍스트 → 【N】 블록 파싱. 죄명·판결요지로 조문 매핑."""
    text = path.read_text(encoding='utf-8')
    blocks = re.split(r'━{5,}', text)

    index = defaultdict(list)
    data = {}

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
        articles |= extract_road_law_articles(ruling)
        for jo in articles:
            index[jo].append(cid)

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
        result.append({
            'doc_id': doc_id,
            'chunk_id': f"{doc_id}-{idx + 1}",
            'title': title,
            'content': content,
            'articles': sorted(extract_road_law_articles(content)),
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
    """학습 가치 가중치 (0~1). 행정심판 + 대법원 판례 수 합산."""
    total = admin_count + court_count
    case_score = math.log(total + 1) / math.log(max_total + 1) if max_total > 0 else 0.0
    if categories:
        cat_score = max(CATEGORY_PRIORITY.get(c, DEFAULT_CATEGORY_PRIORITY) for c in categories)
    else:
        cat_score = DEFAULT_CATEGORY_PRIORITY
    recent_score = 1.0 if has_recent else 0.0
    comment_bonus = 1.0 if has_comment else 0.0
    score = 0.4 * case_score + 0.3 * cat_score + 0.2 * recent_score + 0.1 * comment_bonus
    return {
        'case_score': round(case_score, 3),
        'category_score': round(cat_score, 3),
        'recent_score': round(recent_score, 3),
        'comment_bonus': round(comment_bonus, 3),
        'total': round(score, 3),
    }


def build_article_index(law_index, cases_index, court_index, recent_revised):
    """현행 법령 후보 조문 풀."""
    all_jo = set(law_index) | set(cases_index) | set(court_index)
    max_total = max(
        (len(cases_index.get(j, [])) + len(court_index.get(j, [])) for j in all_jo),
        default=1,
    )
    result = {}
    for jo in all_jo:
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


# ─── 메인 ──────────────────────────────────

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='자료 레지스트리 기반 인덱스 빌더 (M2.6)')
    parser.add_argument('--config', type=str, default=str(CONFIG_PATH))
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

    recent_revised = load_recent_revised(RECENT_REVISIONS_PATH)
    article_index = build_article_index(law_index, cases_index, court_index, recent_revised)

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
