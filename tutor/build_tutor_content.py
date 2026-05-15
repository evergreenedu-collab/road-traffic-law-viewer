"""
출근길 법령 튜터 — 일일 학습 카드 생성 (M2.6 재설계 R3)
=====================================================
하루 1건. --days 옵션으로 여러 날치 한 번에 생성 (테스트용).

자료 균형: 해설집 + 행정심판례 + 대법원·하급심 판례를 모두 LLM 컨텍스트에 제공.
프롬프트 보수화: 원본에 없는 수치·해석 추가 금지 (할루시네이션 최소화),
                법률 용어는 결정문·판결문 표현 그대로.

입력 (tutor/data/, build_indexes.py 산출물):
  index_articles.json, index_law_comment.json,
  index_cases.json, cases_excerpts.json,
  index_court_cases.json, court_cases_data.json
  + ../alarm/data/recent_revisions.json

출력: tutor/data/daily_YYYY-MM-DD.json — 1건 카드

환경변수:
  GEMINI_API_KEY (필수), GEMINI_MODEL (기본 gemini-2.5-flash-lite)

사용법:
  py tutor/build_tutor_content.py --date 2026-05-14            # 1일치
  py tutor/build_tutor_content.py --date 2026-05-14 --days 5   # 5일치
  py tutor/build_tutor_content.py --date 2026-05-14 --dry-run
  py tutor/build_tutor_content.py --date 2026-05-14 --no-llm
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / 'data'

INDEX_LAW = OUTPUT_DIR / 'index_law_comment.json'
INDEX_CASES = OUTPUT_DIR / 'index_cases.json'
CASES_EXCERPTS = OUTPUT_DIR / 'cases_excerpts.json'
INDEX_COURT = OUTPUT_DIR / 'index_court_cases.json'
COURT_DATA = OUTPUT_DIR / 'court_cases_data.json'
INDEX_ARTICLES = OUTPUT_DIR / 'index_articles.json'
INDEX_TOPIC = OUTPUT_DIR / 'index_topic_docs.json'
INPUT_REVISIONS = SCRIPT_DIR.parent / 'alarm' / 'data' / 'recent_revisions.json'

WEIGHT_POOL_SIZE = 40        # 가중치 상위 K개 풀
MAX_ADMIN_CASES = 2          # LLM 컨텍스트에 넣을 행정심판례 수
MAX_COURT_CASES = 2          # LLM 컨텍스트에 넣을 대법원 판례 수
MAX_TOPIC_CHUNKS = 2         # LLM 컨텍스트에 넣을 주제 실무자료 청크 수
CASE_CONTEXT_CHARS = 1400    # 판례 1건당 LLM에 넣을 본문 길이
EPOCH = datetime(2026, 1, 1)

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash-lite').strip()
GEMINI_URL = ('https://generativelanguage.googleapis.com/v1beta/'
              'models/{model}:generateContent?key={key}')
GEMINI_TIMEOUT = 60

TEACHING_KEYWORDS = ('교육', '강의', '수강생', '학습', '교통안전', '훈련', '교습', '안전교육', '교육생')


# ─── 인덱스 로더 ──────────────────────────────────────────────

def load_indexes():
    def _load(path, root, default):
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8')).get(root, default)
        print(f"  ⚠️ {path.name} 없음")
        return default
    idx = {
        'law': _load(INDEX_LAW, '조문별', {}),
        'cases': _load(INDEX_CASES, '조문별', {}),
        'excerpts': _load(CASES_EXCERPTS, '데이터', {}),
        'court_index': _load(INDEX_COURT, '조문별', {}),
        'court_data': _load(COURT_DATA, '데이터', {}),
        'articles': _load(INDEX_ARTICLES, '조문별', {}),
        'topic_docs': _load(INDEX_TOPIC, '청크', []),
        'revisions': None,
    }
    if INPUT_REVISIONS.exists():
        idx['revisions'] = json.loads(INPUT_REVISIONS.read_text(encoding='utf-8'))
    return idx


# ─── 선정 (하루 1건) ──────────────────────────────────────────────

def select_card_for_date(articles, target_date, pool_size=WEIGHT_POOL_SIZE):
    """가중치 상위 풀에서 날짜 기반 결정론적 1건 선택."""
    if not articles:
        return None
    pool = sorted(articles.items(), key=lambda kv: -kv[1].get('weight_score', 0))[:pool_size]
    days = (target_date - EPOCH).days
    idx = days % len(pool)
    jo, info = pool[idx]
    return {
        'jo': jo,
        'info': info,
        'basis': {
            'weight_score': info.get('weight_score', 0),
            'category': (info.get('categories') or ['미분류'])[0],
            'pool_index': idx,
            'pool_size': len(pool),
            'admin_case_count': info.get('admin_case_count', 0),
            'court_case_count': info.get('court_case_count', 0),
        },
    }


def find_resources(jo, indexes, category=None):
    """조문 → 해설 + 행정심판례 + 대법원 판례 + 주제 실무자료 (자료 균형)."""
    law_entry = indexes['law'].get(jo)
    law_comment = law_entry.get('content') if isinstance(law_entry, dict) else None

    # 행정심판례 — 잘린 판례("이하 생략")는 후순위 (원본 cases.json의 OPEN API 잘림 대응)
    admin_pool = []
    for cn in (indexes['cases'].get(jo, []) or [])[:MAX_ADMIN_CASES * 6]:
        ex = indexes['excerpts'].get(cn)
        if not ex:
            continue
        reasoning = ex.get('reasoning', '')
        admin_pool.append(('이하 생략' in reasoning, {
            'type': 'admin',
            'case_no': cn,
            'title': ex.get('title', ''),
            'date': ex.get('date', ''),
            'court': ex.get('court', ''),
            'result': ex.get('result', ''),
            'full_text': reasoning,
        }))
    admin_pool.sort(key=lambda x: x[0])  # 안 잘린 판례(False) 먼저
    admin_cases = [c for _, c in admin_pool[:MAX_ADMIN_CASES]]

    court_cases = []
    for cid in (indexes['court_index'].get(jo, []) or [])[:MAX_COURT_CASES * 5]:
        cd = indexes['court_data'].get(cid)
        if not cd:
            continue
        court_cases.append({
            'type': 'court',
            'case_no': cd.get('case_no', cid),
            'case_name': cd.get('case_name', ''),
            'date': cd.get('date', ''),
            'court': cd.get('court', ''),
            'full_text': cd.get('ruling', ''),
        })
        if len(court_cases) >= MAX_COURT_CASES:
            break

    # 주제 실무자료(수사실무·사고판례집) 청크 매칭 — 조문 직접 인용 우선, 카테고리 차선
    topic_refs = []
    for chunk in indexes.get('topic_docs', []):
        if jo in chunk.get('articles', []):
            topic_refs.append((2, chunk))
        elif category and category in chunk.get('keywords', []):
            topic_refs.append((1, chunk))
    topic_refs.sort(key=lambda x: -x[0])
    topic_docs = [c for _, c in topic_refs[:MAX_TOPIC_CHUNKS]]

    return {
        'law_comment': law_comment,
        'admin_cases': admin_cases,
        'court_cases': court_cases,
        'topic_docs': topic_docs,
    }


def find_recent_revision(jo, revisions):
    if not revisions:
        return None, None
    for v in revisions.get('버전들', []):
        for art in v.get('변경조문', []):
            if art.get('매핑법률조문') == jo:
                return v, art
    return None, None


# ─── Gemini API ──────────────────────────────────────────────

def call_gemini_api(prompt, temperature=0.2, timeout=GEMINI_TIMEOUT,
                    max_retries=3, backoff=(20, 60, 120)):
    if not GEMINI_API_KEY:
        return None
    url = GEMINI_URL.format(model=GEMINI_MODEL, key=GEMINI_API_KEY)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": 4096},
    }
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(url, json=body, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            cands = data.get('candidates', [])
            if not cands:
                return None
            first = cands[0]
            fr = first.get('finishReason', '')
            if fr and fr not in ('STOP', 'FINISH_REASON_STOP'):
                print(f"    ⚠️ finishReason={fr}")
            parts = first.get('content', {}).get('parts', [])
            if not parts:
                return None
            return parts[0].get('text', '').strip()
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if (status == 429 or 500 <= status < 600) and attempt < max_retries:
                wait = backoff[min(attempt, len(backoff) - 1)]
                print(f"    ⏳ status={status} — {wait}초 후 재시도 ({attempt+1}/{max_retries+1})")
                time.sleep(wait)
                continue
            print(f"    ⚠️ Gemini 실패 (status={status})")
            return None
        except requests.RequestException as e:
            print(f"    ⚠️ 네트워크 오류: {type(e).__name__}")
            return None
        except (KeyError, IndexError, ValueError) as e:
            print(f"    ⚠️ 응답 파싱 실패: {type(e).__name__}")
            return None
    return None


def _strip_codeblock(text):
    return re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip(), flags=re.MULTILINE).strip()


# ─── 콘텐츠 생성 (보수화 프롬프트) ──────────────────────────────────────────────

def _build_context(jo, jo_title, version, resources):
    parts = [f"[자료 1: 조문] 도로교통법 제{jo}조 {jo_title}".strip()]

    if version:
        parts.append(
            "[자료 2: 이 조문의 최근 개정]\n"
            f"법령유형: {version.get('법령유형', '')}\n"
            f"공포일자: {version.get('공포일자', '')} / 시행일자: {version.get('시행일자', '')}\n"
            f"제개정구분: {version.get('제개정구분', '')}\n"
            "[제개정 이유 원문]\n"
            f"{version.get('제개정이유', '').strip()}"
        )

    if resources['law_comment']:
        parts.append(f"[자료 3: 도로교통법 해설 — 제{jo}조]\n{resources['law_comment']}")

    if resources['admin_cases']:
        blocks = []
        for c in resources['admin_cases']:
            blocks.append(
                f"- 사건번호 {c['case_no']} | {c['court']} | 결과: {c['result']}\n"
                f"  제목: {c['title']}\n"
                f"  이유: {c['full_text'][:CASE_CONTEXT_CHARS]}"
            )
        parts.append("[자료 4: 관련 행정심판례]\n" + '\n\n'.join(blocks))

    if resources['court_cases']:
        blocks = []
        for c in resources['court_cases']:
            blocks.append(
                f"- 사건번호 {c['case_no']} | {c['court']} ({c['date']})\n"
                f"  사건명: {c['case_name']}\n"
                f"  판결요지: {c['full_text'][:CASE_CONTEXT_CHARS]}"
            )
        parts.append("[자료 5: 관련 대법원·하급심 판례]\n" + '\n\n'.join(blocks))

    if resources.get('topic_docs'):
        blocks = []
        for t in resources['topic_docs']:
            blocks.append(f"- 출처: {t['doc_id']} — {t['title']}\n  {t['content'][:1100]}")
        parts.append(
            "[자료 6: 실무 참고자료 (수사실무연구·사고조사판례집)]\n"
            "(실무 쟁점·사례 참고용. 사건번호 인용 대상 아님)\n"
            + '\n\n'.join(blocks)
        )

    return '\n\n'.join(parts)


def generate_learning_content(jo, jo_title, version, resources):
    context = _build_context(jo, jo_title, version, resources)
    has_cases = bool(resources['admin_cases'] or resources['court_cases'])

    prompt = f"""당신은 한국도로교통공단 교수의 학습 콘텐츠 작성자입니다. 교수들이 매일 아침 읽는 자료이므로 정확성이 최우선입니다.

[작성 규칙 — 위반 시 자료 신뢰도 훼손, 반드시 지킬 것]
1. 아래 원본 자료에 명시된 사실만 사용한다. 자료에 없는 수치·기간·해석·사례는 절대 추가하지 않는다.
   - 예: 개정 이유 원문에 갱신 기간 같은 구체적 수치가 없으면 그런 수치를 지어내거나 추론하지 않는다.
2. 확실하지 않은 부분은 생략한다. 추측·일반론을 적느니 생략하는 것이 낫다.
3. 법률 용어는 자료의 결정문·판결문 표현을 그대로 쓴다. 일상어로 의역하지 않는다.
4. 인용 사건번호는 [자료 4]·[자료 5]에 있는 것만 사용한다.
5. case_analysis는 [자료 4]·[자료 5]의 실제 사건(처분 내용·당사자 주장·판단 근거·결론)만 기술한다.
6. 단정·일반화 표현 금지. 판례의 결론은 그 사건의 특정 사실관계(특정 신호 상황, 특정 처분 등)에 한정된다.
   '항상', '무관하게', '반드시', '모든 경우', '예외 없이' 같은 일반화는 원본 자료가 명확히 그렇게 규정할 때만 쓴다.
   불명확하면 '~될 수 있다', '~한 경우', '~로 볼 여지가 있다' 등 유보적 표현을 쓴다.
   (예: 녹색점멸 신호 상황의 판례를 '신호와 무관하게 보호'처럼 일반화하지 말 것)

[원본 자료]
{context}

[출력 — 아래 JSON만. 마크다운 코드블록·설명 없이]
{{
  "status": "ok",
  "oneliner": "조문 핵심 한 줄 (50자 이내, 의무·금지·기준 중심. 개정 내용을 단정적으로 요약하지 말 것)",
  "explanation": "조문 해설 (200자 이내, 자료 3 해설 또는 조문 자체 기반. 자료에 근거 없는 서술 금지)",
  "source_article": "도로교통법 제{jo}조",
  "case_analysis": "판례·행정심판 분석 (350자 이내, 자료 4·5 기반: 어떤 처분/기소였는지, 당사자 주장, 인용/기각·유죄/무죄 등 결론과 그 법리적 근거. 법률 용어 정확히)",
  "teaching_application": "교통안전교육 적용 (150자 이내, 어떤 교육·강의에서 어떻게 활용할지. '교육'·'강의'·'수강생' 등 단어 포함)",
  "related_cases": [
    {{"case_no": "자료의 사건번호", "type": "admin 또는 court", "title": "사건 제목·사건명 요약", "result": "결과(인용/기각/유죄/무죄/파기 등)", "lesson": "이 사건의 학습 포인트 1줄 (60자 이내)"}}
  ],
  "key_issues": ["핵심 쟁점 1 (60자 이내)", "핵심 쟁점 2 (60자 이내)"],
  "study_points": ["강의 활용 포인트 1 (80자 이내)", "강의 활용 포인트 2 (80자 이내)"]
}}

조건부:
- [자료 4]·[자료 5]가 없으면 case_analysis는 "관련 판례 자료 없음", related_cases는 []
- 자료가 학습 콘텐츠 작성에 부족하면: {{"status": "skip", "reason": "이유"}}
"""
    response = call_gemini_api(prompt, temperature=0.2)
    if response is None:
        return None
    try:
        return json.loads(_strip_codeblock(response))
    except json.JSONDecodeError as e:
        print(f"    ⚠️ JSON 파싱 실패: {e}")
        print(f"    raw: {response[:200]}")
        return None


def verify_content(generated, jo, resources):
    """코드 자기검증."""
    if not generated or generated.get('status') != 'ok':
        return 'SKIP_NO_CONTENT'

    expected_jo = f'제{jo}조'
    for field in ('oneliner', 'explanation', 'source_article', 'case_analysis', 'teaching_application'):
        v = generated.get(field, '')
        if not isinstance(v, str) or not v.strip():
            return f'FAIL_field_empty:{field}'

    if expected_jo not in generated['source_article']:
        return f'FAIL_source_article:expected={expected_jo}'

    limits = {'oneliner': 90, 'explanation': 320, 'case_analysis': 480, 'teaching_application': 220}
    for f, lim in limits.items():
        if len(generated[f]) > lim:
            return f'FAIL_{f}_too_long:{len(generated[f])}'

    if not any(kw in generated['teaching_application'] for kw in TEACHING_KEYWORDS):
        return f'FAIL_teaching_no_keyword'

    # 인용 사건번호 검증 (행정심판 + 대법원 통합)
    allowed = {c['case_no'] for c in resources['admin_cases']}
    allowed |= {c['case_no'] for c in resources['court_cases']}
    rc = generated.get('related_cases', [])
    if not isinstance(rc, list):
        return 'FAIL_related_cases_not_list'
    for i, c in enumerate(rc):
        if not isinstance(c, dict):
            return f'FAIL_related_case_not_dict:{i}'
        cn = c.get('case_no', '')
        if cn and cn not in allowed:
            return f'FAIL_invented_case_no:{cn}'

    for lf in ('key_issues', 'study_points'):
        items = generated.get(lf, [])
        if not isinstance(items, list):
            return f'FAIL_{lf}_not_list'
        for j, it in enumerate(items):
            if not isinstance(it, str) or not it.strip():
                return f'FAIL_{lf}_invalid:{j}'

    return 'PASS'


def enrich_card(card, jo, jo_title, version, resources):
    if not GEMINI_API_KEY:
        card['llm_status'] = 'skip_no_api_key'
        return
    n_admin = len(resources['admin_cases'])
    n_court = len(resources['court_cases'])
    print(f"  🤖 제{jo}조 LLM 호출 (해설{'✓' if resources['law_comment'] else '✗'} · 행정심판 {n_admin} · 대법원 {n_court})")
    generated = generate_learning_content(jo, jo_title, version, resources)
    if not generated:
        card['llm_status'] = 'skip_call_failed'
        return
    if generated.get('status') != 'ok':
        card['llm_status'] = 'skip_llm_returned_skip'
        card['llm_note'] = generated.get('reason', '')
        return
    verdict = verify_content(generated, jo, resources)
    if verdict != 'PASS':
        card['llm_status'] = 'skip_verification_failed'
        card['llm_note'] = verdict
        card['llm_draft'] = generated
        print(f"    ❌ {verdict}")
        return
    print(f"    ✅ PASS")
    card['learning_content'] = {
        'oneliner': generated['oneliner'],
        'explanation': generated['explanation'],
        'source_article': generated['source_article'],
        'case_analysis': generated['case_analysis'],
        'teaching_application': generated['teaching_application'],
        'related_cases': generated.get('related_cases', []),
        'key_issues': generated.get('key_issues', []),
        'study_points': generated.get('study_points', []),
    }
    card['llm_status'] = 'ok'


# ─── 카드/일일 빌드 ──────────────────────────────────────────────

def build_card(selection, indexes, use_llm=True):
    jo = selection['jo']
    jo_entry = indexes['law'].get(jo)
    jo_title = jo_entry.get('title', '') if isinstance(jo_entry, dict) else ''

    version, changed = find_recent_revision(jo, indexes['revisions'])
    resources = find_resources(jo, indexes, selection['basis'].get('category'))

    card = {
        'card_id': 'card-1',
        'rank': 1,
        'selection_basis': selection['basis'],
        'law_info': {
            '매핑법률조문': jo,
            '매핑법률조문제목': jo_title,
            'is_recent_revision': version is not None,
            'categories': selection['info'].get('categories', []),
            'viewer_link': f'../viewer.html?jo={jo}',
            'resources_found': {
                'has_law_comment': resources['law_comment'] is not None,
                'admin_cases_count': len(resources['admin_cases']),
                'court_cases_count': len(resources['court_cases']),
            },
        },
    }
    if version:
        card['law_info']['recent_revision'] = {
            '법령유형': version.get('법령유형'),
            '법령명': version.get('법령명'),
            '공포일자': version.get('공포일자'),
            '시행일자': version.get('시행일자'),
            '제개정구분': version.get('제개정구분'),
            '제개정이유_원본': version.get('제개정이유', '').strip(),
        }

    # UI 전문 펼침용 (행정심판 + 대법원 통합)
    card['related_cases_full'] = [
        {
            'type': c['type'],
            'case_no': c['case_no'],
            'title': c.get('title') or c.get('case_name', ''),
            'date': c.get('date', ''),
            'court': c.get('court', ''),
            'result': c.get('result', ''),
            'full_text': c['full_text'],
        }
        for c in (resources['admin_cases'] + resources['court_cases'])
    ]

    # R5.5: 자료 출처 가시화 — 해설집·실무자료를 카드에 기록 (UI '참고 자료' 표시용)
    card['source_materials'] = {
        'law_comment': (resources['law_comment'][:700] if resources['law_comment'] else None),
        'topic_docs': [
            {
                'doc_id': t.get('doc_id', ''),
                'title': t.get('title', ''),
                'excerpt': (t.get('content', '') or '')[:500],
            }
            for t in resources.get('topic_docs', [])
        ],
    }

    if use_llm:
        enrich_card(card, jo, jo_title, version, resources)
    else:
        card['llm_status'] = 'skipped_by_flag'

    return card


def build_daily(target_date, indexes, use_llm=True):
    base = {
        'date': target_date.strftime('%Y-%m-%d'),
        'generated_at': datetime.now().isoformat(),
        'milestone': 'M2.6',
        'version': 5,
    }
    if not indexes['articles']:
        base['status'] = 'skip'
        base['reason'] = 'index_articles.json 없음'
        return base

    selection = select_card_for_date(indexes['articles'], target_date)
    if not selection:
        base['status'] = 'skip'
        base['reason'] = '선정 후보 없음'
        return base

    b = selection['basis']
    print(f"\n📅 {target_date.strftime('%Y-%m-%d')} → 제{selection['jo']}조 "
          f"(w={b['weight_score']:.3f}, {b['category']}, "
          f"행정심판 {b['admin_case_count']}·대법원 {b['court_case_count']})")

    card = build_card(selection, indexes, use_llm=use_llm)
    base['status'] = 'ok'
    base['cards'] = [card]
    return base


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='일일 학습 카드 생성 (M2.6 R3)')
    parser.add_argument('--date', type=str, default=None, help='시작 날짜 YYYY-MM-DD')
    parser.add_argument('--days', type=int, default=1, help='며칠치 생성 (기본 1)')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--no-llm', action='store_true')
    args = parser.parse_args()

    if args.date:
        try:
            start_date = datetime.strptime(args.date, '%Y-%m-%d')
        except ValueError:
            print(f"❌ --date 형식 오류: '{args.date}'")
            sys.exit(1)
    else:
        start_date = datetime.now()

    print("=" * 60)
    print(f"  📚 일일 학습 카드 생성 (M2.6 R3) — {start_date.strftime('%Y-%m-%d')} 부터 {args.days}일치")
    print("=" * 60)
    if args.no_llm:
        print("⏭️ --no-llm")
    elif GEMINI_API_KEY:
        print(f"🔑 GEMINI_API_KEY 감지 (model={GEMINI_MODEL})")
    else:
        print("⚠️ GEMINI_API_KEY 없음")

    indexes = load_indexes()
    print(f"📚 인덱스: 해설 {len(indexes['law'])} · 행정심판 {len(indexes['cases'])} · "
          f"대법원 {len(indexes['court_index'])} · 후보풀 {len(indexes['articles'])}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    # 여러 날치 생성 시 카드 간 간격 (분당 한도 429 회피). 1일치·--no-llm은 대기 없음.
    gap = 25 if (args.days > 1 and not args.no_llm) else 0
    results = []
    for d in range(args.days):
        if d > 0 and gap:
            print(f"  ⏳ 분당 한도 회피 — {gap}초 대기")
            time.sleep(gap)
        target = start_date + timedelta(days=d)
        content = build_daily(target, indexes, use_llm=not args.no_llm)
        results.append((target, content))

        if not args.dry_run:
            out = OUTPUT_DIR / f"daily_{target.strftime('%Y-%m-%d')}.json"
            with open(out, 'w', encoding='utf-8') as f:
                json.dump(content, f, ensure_ascii=False, indent=2)
            size_kb = out.stat().st_size / 1024
            print(f"  💾 {out.name} ({size_kb:.0f}KB)")

    print("\n📊 요약:")
    for target, content in results:
        if content.get('status') == 'ok' and content.get('cards'):
            card = content['cards'][0]
            jo = card['law_info']['매핑법률조문']
            status = card.get('llm_status', '?')
            mark = '✅' if status == 'ok' else '⚠️'
            line = f"  {mark} {target.strftime('%Y-%m-%d')} 제{jo}조 — {status}"
            if status == 'ok':
                line += f" — {card['learning_content']['oneliner']}"
            print(line)
        else:
            print(f"  ⚠️ {target.strftime('%Y-%m-%d')} — {content.get('status')}")

    if args.dry_run:
        print("\n📋 --dry-run: 파일 미저장")


if __name__ == '__main__':
    main()
