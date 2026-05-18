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
import math
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
INDEX_LAW_ARTICLES = OUTPUT_DIR / 'index_law_articles.json'  # 현행 조문 본문
INDEX_LAW_HISTORY = OUTPUT_DIR / 'index_law_history.json'    # 조문별 실질 개정 시행일 (R9-3)
SCHEDULE_PATH = OUTPUT_DIR / 'schedule.json'                 # 날짜→조문 고정 (R8 E)
INPUT_REVISIONS = SCRIPT_DIR.parent / 'alarm' / 'data' / 'recent_revisions.json'

WEIGHT_POOL_SIZE = 40        # 가중치 상위 K개 풀
MAX_ADMIN_CASES = 2          # 카드에 최종 노출할 행정심판례 수 (관련성 필터 후)
MAX_COURT_CASES = 2          # 카드에 최종 노출할 대법원 판례 수 (관련성 필터 후)
CAND_ADMIN = 5               # 관련성 필터에 넘길 행정심판례 후보 수 (R10-4)
CAND_COURT = 6               # 관련성 필터에 넘길 대법원 판례 후보 수 (R10-4)
MAX_TOPIC_CHUNKS = 2         # LLM 컨텍스트에 넣을 주제 실무자료 청크 수
CASE_CONTEXT_CHARS = 1400    # 판례 1건당 LLM에 넣을 본문 길이
EPOCH = datetime(2026, 1, 1)

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash-lite').strip()
GEMINI_URL = ('https://generativelanguage.googleapis.com/v1beta/'
              'models/{model}:generateContent?key={key}')
GEMINI_TIMEOUT = 60

TEACHING_KEYWORDS = ('교육', '강의', '수강생', '학습', '교통안전', '훈련', '교습', '안전교육', '교육생')

# R7-6: 자료 근거 없이 쓰면 안 되는 위험한 일반화 표현 (판례 결론은 사실관계에 한정)
HARD_GENERALIZATIONS = ('무관하게', '예외 없이', '예외없이', '모든 경우에', '어떤 경우에도')


# R8 C3: 판례 제목에 남길 도로교통·교통 관련 죄명 키워드
TRAFFIC_TITLE_KEYWORDS = ('도로교통법', '교통사고', '교통', '운전', '도주치', '자동차', '음주', '무면허')


def clean_case_title(name):
    """경합범 판례 사건명에서 도로교통·교통 관련 죄명만 남김 (다른 죄명 제거).
    전부 제거되면 원본 유지 — 빈 제목 방지 (원본 case_name은 인덱스에 보존)."""
    if not name or '·' not in name:
        return name
    parts = [p.strip() for p in name.split('·') if p.strip()]
    kept = [p for p in parts if any(k in p for k in TRAFFIC_TITLE_KEYWORDS)]
    return '·'.join(kept) if kept else name


def parse_date_tuple(s):
    """날짜 문자열 → (년, 월, 일) 튜플. '2023.06.29'·'20230101'·'2023-1-9' 등. 실패 시 None."""
    if not s:
        return None
    raw = str(s).strip()
    if re.fullmatch(r'\d{8}', raw):
        return (int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    m = re.search(r'(\d{4})\D{1,3}(\d{1,2})\D{1,3}(\d{1,2})', raw)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


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
        'law_articles': _load(INDEX_LAW_ARTICLES, '조문별', {}),
        'law_history': _load(INDEX_LAW_HISTORY, '조문별', {}),
        'revisions': None,
    }
    if INPUT_REVISIONS.exists():
        idx['revisions'] = json.loads(INPUT_REVISIONS.read_text(encoding='utf-8'))
    return idx


def load_schedule():
    """날짜→조문 고정표. 없으면 빈 dict (R8 E — 인덱스가 바뀌어도 기존 배정 유지)."""
    if SCHEDULE_PATH.exists():
        try:
            return json.loads(SCHEDULE_PATH.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            print("  ⚠️ schedule.json 손상 — 새로 시작")
    return {}


def save_schedule(schedule):
    SCHEDULE_PATH.write_text(
        json.dumps(schedule, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')


# ─── 선정 (하루 1건) ──────────────────────────────────────────────

def select_card_for_date(articles, target_date, schedule, pool_size=WEIGHT_POOL_SIZE):
    """날짜→조문 선정 (R8 E). schedule.json에 한 번 배정되면 인덱스가 바뀌어도 고정.

    신규 날짜는 가중치 상위 풀에서 보폭(stride) 순회로 결정론적 배정 —
    연속한 날짜가 가중치 인접 조문에 쏠리지 않게 흩어 순회.
    """
    if not articles:
        return None
    key = target_date.strftime('%Y-%m-%d')
    jo = schedule.get(key)
    if not jo or jo not in articles:
        pool = sorted(articles.items(), key=lambda kv: -kv[1].get('weight_score', 0))[:pool_size]
        n = len(pool)
        days = (target_date - EPOCH).days
        stride = 7
        while stride > 1 and math.gcd(stride, n) != 1:
            stride -= 1
        jo = pool[(days * stride) % n][0]
        schedule[key] = jo  # 신규 배정 — 이후 인덱스가 바뀌어도 이 날짜는 이 조문 고정
    info = articles[jo]
    return {
        'jo': jo,
        'info': info,
        'basis': {
            'weight_score': info.get('weight_score', 0),
            'category': (info.get('categories') or ['미분류'])[0],
            'admin_case_count': info.get('admin_case_count', 0),
            'court_case_count': info.get('court_case_count', 0),
        },
    }


def find_resources(jo, indexes, category=None, jo_title=''):
    """조문 → 해설 + 행정심판례 + 대법원 판례 + 주제 실무자료 (자료 균형)."""
    law_entry = indexes['law'].get(jo)
    law_comment = law_entry.get('content') if isinstance(law_entry, dict) else None

    # 행정심판례 — 잘린 판례("이하 생략")는 후순위 (원본 cases.json의 OPEN API 잘림 대응)
    admin_pool = []
    for cn in (indexes['cases'].get(jo, []) or [])[:CAND_ADMIN * 3]:
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
    admin_cases = [c for _, c in admin_pool[:CAND_ADMIN]]

    court_cases = []
    for cid in (indexes['court_index'].get(jo, []) or [])[:CAND_COURT * 3]:
        cd = indexes['court_data'].get(cid)
        if not cd:
            continue
        court_cases.append({
            'type': 'court',
            'case_no': cd.get('case_no', cid),
            'case_name': clean_case_title(cd.get('case_name', '')),
            'date': cd.get('date', ''),
            'court': cd.get('court', ''),
            'full_text': cd.get('ruling', ''),
        })
        if len(court_cases) >= CAND_COURT:
            break

    # 주제 실무자료(수사실무·사고판례집) 청크 매칭 — 점수식 (R13-C):
    # 조문 직접 인용 +2 / 없음 -2, 카테고리 일치 +1·충돌 -1, 제목 키워드 일치 +1.
    # 주제 정합 신호(카테고리·제목)가 전무하면 -1. 합계 2점 이상 청크만 채택 —
    # 조문과 무관한 실무자료가 카드에 인용되던 문제(05-15 음주 카드에 어린이보호구역) 차단.
    def _stem(w):
        return re.sub(r'(으로|에서|에게|의|을|를|이|가|은|는|에|와|과|로|도)$', '', w)
    title_words = [t for t in (_stem(w) for w in re.split(r'[\s·,()/-]+', jo_title or ''))
                   if len(t) >= 2]
    topic_refs = []
    for chunk in indexes.get('topic_docs', []):
        kws = chunk.get('keywords', []) or []
        ctitle = chunk.get('title', '') or ''
        score = 2 if jo in chunk.get('articles', []) else -2
        topical = False
        if category and category in kws:
            score += 1
            topical = True
        elif category and kws and category not in kws:
            score -= 1
        if title_words and any(w in ctitle for w in title_words):
            score += 1
            topical = True
        if not topical:
            score -= 1
        if score >= 2:
            topic_refs.append((score, chunk))
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
    # 섹션 머리표는 자연스러운 이름으로 — LLM이 '자료 N' 같은 내부 라벨을
    # 답변에 그대로 노출하던 문제(R12-C)를 원천 차단.
    parts = [f"[조문] 도로교통법 제{jo}조 {jo_title}".strip()]

    if version:
        parts.append(
            "[이 조문의 최근 개정 정보]\n"
            f"법령유형: {version.get('법령유형', '')}\n"
            f"공포일자: {version.get('공포일자', '')} / 시행일자: {version.get('시행일자', '')}\n"
            f"제개정구분: {version.get('제개정구분', '')}\n"
            "[제개정 이유 원문]\n"
            f"{version.get('제개정이유', '').strip()}"
        )

    if resources['law_comment']:
        parts.append(f"[도로교통법 해설집 — 제{jo}조]\n{resources['law_comment']}")

    if resources['admin_cases']:
        blocks = []
        for c in resources['admin_cases']:
            blocks.append(
                f"- 사건번호 {c['case_no']} | {c['court']} | 결과: {c['result']}\n"
                f"  제목: {c['title']}\n"
                f"  이유: {c['full_text'][:CASE_CONTEXT_CHARS]}"
            )
        parts.append("[관련 행정심판례]\n" + '\n\n'.join(blocks))

    if resources['court_cases']:
        blocks = []
        for c in resources['court_cases']:
            blocks.append(
                f"- 사건번호 {c['case_no']} | {c['court']} ({c['date']})\n"
                f"  사건명: {c['case_name']}\n"
                f"  판결요지: {c['full_text'][:CASE_CONTEXT_CHARS]}"
            )
        parts.append("[관련 판례 (대법원·하급심)]\n" + '\n\n'.join(blocks))

    if resources.get('topic_docs'):
        blocks = []
        for t in resources['topic_docs']:
            blocks.append(f"- 출처: {t['doc_id']} — {t['title']}\n  {t['content'][:1100]}")
        parts.append(
            "[실무 참고자료 (수사실무연구·사고조사판례집)]\n"
            "(실무 쟁점·사례 참고용. 사건번호 인용 대상 아님)\n"
            + '\n\n'.join(blocks)
        )

    return '\n\n'.join(parts)


def generate_learning_content(jo, jo_title, version, resources):
    context = _build_context(jo, jo_title, version, resources)
    has_cases = bool(resources['admin_cases'] or resources['court_cases'])
    if has_cases:
        path = ('이 조문에는 직접 관련된 판례가 제공되었다. analysis_type을 "case"로 하고, '
                'related_cases를 채우며 case_analysis는 규칙 5대로 사건을 요약 분석한다.')
    else:
        path = ('이 조문에는 직접 관련된 판례가 제공되지 않았다. analysis_type을 "commentary"로 하고, '
                'related_cases는 []로 둔다. case_analysis는 해설집과 실무 참고자료에서 이 조문 학습의 '
                '핵심을 골라 충실히 가르치는 "학습 해설"로 쓴다(700~1000자). 판례가 없다는 사실은 '
                '언급하지 않는다 — 해설집은 경찰 교육용 정식 자료이므로 그것만으로 완결된 학습이 되게 한다. '
                '특정 사건번호(예: 2017도1234)는 인용하지 않는다 — 펼쳐볼 판례 자료가 없으므로 '
                '법리·기준 중심으로 서술한다.')

    prompt = f"""당신은 한국도로교통공단 교수의 학습 콘텐츠 작성자입니다. 교수들이 매일 아침 읽는 자료이므로 정확성이 최우선입니다.

[작성 규칙 — 위반 시 자료 신뢰도 훼손, 반드시 지킬 것]
1. 아래 원본 자료에 명시된 사실만 사용한다. 자료에 없는 수치·기간·해석·사례는 추가하지 않는다.
2. 확실하지 않은 부분은 생략한다. 추측·일반론을 적느니 생략하는 것이 낫다.
3. 법률 용어는 자료의 결정문·판결문·해설집 표현을 그대로 쓴다. 일상어로 의역하지 않는다.
4. 인용 사건번호는 [관련 행정심판례]·[관련 판례] 섹션에 있는 것만 쓴다.
   [도로교통법 해설집]·[실무 참고자료] 본문 안에 등장하는 사건번호는 case_analysis를
   비롯해 어디에도 절대 쓰지 않는다 — 그 판례 전문이 카드에 없어 펼쳐볼 수 없기 때문이다.
5. case_analysis가 판례 분석일 때: 사건당 2~3문장으로 간결히 요약한다
   (어떤 처분/기소 → 핵심 쟁점 → 결론과 근거). 결정문·판결문을 길게 옮기지 말 것.
   사건이 둘 이상이면 '1) 사건번호 — …', '2) 사건번호 — …'로 번호 문단을 나눈다.
6. 단정·일반화 표현 금지. 판례의 결론은 그 사건의 특정 사실관계에 한정된다.
   '항상'·'무관하게'·'반드시'·'모든 경우'·'예외 없이' 같은 일반화는 자료가 명확히 그렇게
   규정할 때만 쓴다. 불명확하면 '~될 수 있다'·'~한 경우' 등 유보적 표현을 쓴다.
7. 이 조문(제{jo}조)의 핵심 주제와 직접 관련된 판례만 related_cases·case_analysis에 넣는다.
   조문을 관계법령으로 한 번 언급한 정도이거나 사건 본질이 다른 주제면 제외한다.
8. ★출력에 내부 라벨을 절대 노출하지 않는다 — '자료 1/2/3'·'[자료 N]'·'원본 자료'·
   '제시된 자료' 같은 표현 금지. 출처를 밝힐 땐 '해설집에 따르면'·'수사실무 자료에서는'
   처럼 자연스러운 이름으로 쓴다.
9. ★메타 서술 금지 — '관련 판례가 없습니다'·'판례가 제시되지 않았습니다'·'판례 없음'처럼
   자료의 유무를 설명하는 문장을 절대 쓰지 않는다. 판례가 없으면 그 사실을 언급하지 말고
   곧장 해설집 내용으로 충실히 가르친다.
10. ★case_analysis는 통짜로 쓰지 않는다 — 의미 단위로 문단을 나누고 문단과 문단 사이를
   빈 줄(줄바꿈 2개)로 구분한다. 한 문단은 3~5문장을 넘지 않게 한다. 기간·요건처럼
   열거되는 내용(예: 결격기간 1년/2년/3년/5년 사유)은 각 항목을 줄바꿈해 나열한다.

[이 카드의 작성 경로]
{path}

[원본 자료]
{context}

[출력 — 아래 JSON만. 마크다운 코드블록·설명 없이]
{{
  "status": "ok",
  "analysis_type": "case 또는 commentary (위 작성 경로대로)",
  "oneliner": "조문 핵심 한 줄 (50자 이내, 의무·금지·기준 중심. 개정 내용을 단정 요약하지 말 것)",
  "explanation": "조문 해설 (200자 이내, 해설집 또는 조문 자체 기반. 근거 없는 서술 금지)",
  "source_article": "도로교통법 제{jo}조",
  "case_analysis": "analysis_type=case면 판례 요약 분석 / commentary면 해설집 기반 학습 해설. 700~1000자. 의미 단위 문단으로 — 문단 사이 빈 줄, 통짜 금지",
  "teaching_application": "교통안전교육 적용 (150자 이내, 어떤 교육·강의에서 어떻게 활용할지. '교육'·'강의'·'수강생' 등 단어 포함)",
  "related_cases": [
    {{"case_no": "사건번호", "type": "admin 또는 court", "title": "사건 제목·사건명 요약", "result": "결과(인용/기각/유죄/무죄/파기 등)", "lesson": "이 사건의 학습 포인트 1줄 (60자 이내)"}}
  ],
  "key_issues": ["핵심 쟁점 1 (60자 이내)", "핵심 쟁점 2 (60자 이내)"],
  "study_points": ["강의 활용 포인트 1 (80자 이내)", "강의 활용 포인트 2 (80자 이내)"]
}}

자료가 학습 콘텐츠 작성에 부족하면: {{"status": "skip", "reason": "이유"}}
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
    for field in ('oneliner', 'explanation', 'source_article', 'teaching_application'):
        v = generated.get(field, '')
        if not isinstance(v, str) or not v.strip():
            return f'FAIL_field_empty:{field}'
    # case_analysis는 제공된 판례가 0건일 때만 비어도 허용 (R9-6 — 해설집 기반 카드)
    ca = generated.get('case_analysis', '')
    if not isinstance(ca, str):
        return 'FAIL_field_empty:case_analysis'
    has_cases = bool(resources['admin_cases'] or resources['court_cases'])
    if not ca.strip() and has_cases:
        return 'FAIL_field_empty:case_analysis'

    if expected_jo not in generated['source_article']:
        return f'FAIL_source_article:expected={expected_jo}'

    # case_analysis는 요약체 — 사건당 2~3문장. 한도 1000자 (R9-2)
    limits = {'oneliner': 90, 'explanation': 320, 'case_analysis': 1000, 'teaching_application': 220}
    for f, lim in limits.items():
        if len(generated.get(f, '')) > lim:
            return f'FAIL_{f}_too_long:{len(generated.get(f, ""))}'

    if not any(kw in generated['teaching_application'] for kw in TEACHING_KEYWORDS):
        return f'FAIL_teaching_no_keyword'

    # 인용 사건번호 검증 (행정심판 + 대법원 통합)
    case_dates = {c['case_no']: c.get('date', '')
                  for c in resources['admin_cases'] + resources['court_cases']}
    allowed = set(case_dates)
    rc = generated.get('related_cases', [])
    if not isinstance(rc, list):
        return 'FAIL_related_cases_not_list'
    # 자료에 없는 사건번호(해설집 본문 인용 등)는 그 항목만 제외하고 카드는 살림 (R9)
    clean_rc = []
    for c in rc:
        if not isinstance(c, dict):
            continue
        cn = c.get('case_no', '')
        if cn and cn not in allowed:
            continue
        clean_rc.append(c)
    generated['related_cases'] = clean_rc

    for lf in ('key_issues', 'study_points'):
        items = generated.get(lf, [])
        if not isinstance(items, list):
            return f'FAIL_{lf}_not_list'
        for j, it in enumerate(items):
            if not isinstance(it, str) or not it.strip():
                return f'FAIL_{lf}_invalid:{j}'

    # R7-6/R12: 위험 일반화·메타 라벨 검사 대상 — 화면 노출 텍스트 전체
    # (teaching_application·related_cases 제목/교훈 포함 — Codex 지적).
    rc_text = ' '.join(
        ((c.get('title', '') or '') + ' ' + (c.get('lesson', '') or ''))
        for c in (generated.get('related_cases', []) or []) if isinstance(c, dict))
    scan = ' '.join([
        generated.get('oneliner', ''),
        generated.get('explanation', ''),
        generated.get('case_analysis', ''),
        generated.get('teaching_application', ''),
        ' '.join(generated.get('key_issues', []) or []),
        ' '.join(generated.get('study_points', []) or []),
        rc_text,
    ])
    for w in HARD_GENERALIZATIONS:
        if w in scan:
            return f'FAIL_overgeneralization:{w}'

    # R12-C: 내부 라벨·메타 서술 차단 — '[자료 N]'·'판례 없음'·'판례가 제시되지 않' 등은
    # 생성이 자료를 안 쓰고 메타 설명만 한 결함. 검출 시 검증 실패 처리.
    for pat in (r'\[자료', r'원본\s*자료', r'제시된\s*자료', r'판례\s*없음',
                r'판례[^.,\n]{0,12}제시되지\s*않', r'관련[^.,\n]{0,4}판례[^.,\n]{0,4}없'):
        if re.search(pat, scan):
            return f'FAIL_meta_label:{pat}'

    # R12-D: case_analysis가 자료에 없는 사건번호를 인용하면 실패 — 전문 펼침 불가 +
    # analysis_type 오분류(인용 판례가 있는데 commentary로 표시되는 것) 방지.
    cited = set(re.findall(r'\d{4}[가-힣]{1,3}\d+', generated.get('case_analysis', '')))
    unknown = cited - allowed
    if unknown:
        return f'FAIL_uncited_case:{sorted(unknown)[0]}'

    # R12-C: 해설집이 있는데 case_analysis가 빈약하면 실패 (품질 게이트)
    if resources['law_comment'] and len(generated.get('case_analysis', '').strip()) < 200:
        return 'FAIL_thin_analysis'

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
    rc = generated.get('related_cases', [])
    # R12-D: case_analysis가 언급한 사건번호가 related_cases에 빠졌으면 보강 —
    # UI 전문 펼침이 related_cases 기준이라, 누락 시 인용 판례를 못 펼침.
    allowed = {c['case_no']: c
               for c in resources['admin_cases'] + resources['court_cases'] if c.get('case_no')}
    rc_nos = {c.get('case_no') for c in rc if isinstance(c, dict)}
    ca_text = generated.get('case_analysis', '')
    for cn, src in allowed.items():
        if cn in ca_text and cn not in rc_nos:
            rc.append({
                'case_no': cn,
                'type': src.get('type', ''),
                'title': src.get('title') or src.get('case_name', ''),
                'result': src.get('result', ''),
                'lesson': '',
            })
            rc_nos.add(cn)
    # R12-C: analysis_type은 코드가 확정 — 관련 판례 유무 기준 (LLM 값 신뢰 안 함)
    card['learning_content'] = {
        'oneliner': generated['oneliner'],
        'explanation': generated['explanation'],
        'source_article': generated['source_article'],
        'case_analysis': generated['case_analysis'],
        'teaching_application': generated['teaching_application'],
        'related_cases': rc,
        'analysis_type': 'case' if rc else 'commentary',
        'key_issues': generated.get('key_issues', []),
        'study_points': generated.get('study_points', []),
    }
    card['llm_status'] = 'ok'


# ─── 카드/일일 빌드 ──────────────────────────────────────────────

def revision_after(jo, case_date, law_history):
    """jo 조문이 case_date 이후 실질 개정(시행)됐으면 가장 이른 개정 연도, 없으면 None (R9-3)."""
    cd = parse_date_tuple(case_date)
    if not cd:
        return None
    years = []
    for rev in law_history.get(jo, []):
        rd = parse_date_tuple(rev.get('시행일자'))
        if rd and rd > cd:
            years.append(rd[0])
    return min(years) if years else None


def inject_history_notes(card, jo, resources, law_history):
    """related_cases에 연혁 주의(history_note)를 코드가 결정론적으로 주입 (R9-3).
    판례 확정일 이후 조문이 실질 개정됐을 때만 표시 — 변경 없으면 표시하지 않는다."""
    lc = card.get('learning_content')
    if not lc:
        return
    case_dates = {c['case_no']: c.get('date', '')
                  for c in resources['admin_cases'] + resources['court_cases']}
    for rc in lc.get('related_cases', []):
        if not isinstance(rc, dict):
            continue
        yr = revision_after(jo, case_dates.get(rc.get('case_no', '')), law_history)
        rc['history_note'] = (
            f"이 판례는 {yr}년 개정 이전 사안 — 인용 조문이 그 뒤 개정되어 현행 적용 시 확인 필요"
            if yr else '')


def _case_relevance_score(jo, jo_title, case):
    """코드 관련성 점수 — 사건명·본문에 조문번호/제목 키워드가 있으면 가점 (R9-5 fallback)."""
    text = (case.get('case_name', '') + ' ' + case.get('title', '')
            + ' ' + (case.get('full_text', '') or '')[:600])
    score = 2 if f'제{jo}조' in text else 0
    for word in re.findall(r'[가-힣]{2,}', jo_title or ''):
        if word in text:
            score += 1
    return score


def filter_relevant_cases(jo, jo_title, resources):
    """관련성 사전 필터 (R9-5) — 조문 핵심 주제와 직접 관련된 판례만 남긴다.
    단일 과제 LLM 필터 + 실패·파싱오류 시 코드 점수 상위로 fallback (원 후보 전체 X)."""
    cases = resources['admin_cases'] + resources['court_cases']
    if len(cases) <= 1:
        return resources
    listing = []
    for c in cases:
        name = c.get('case_name') or c.get('title', '')
        listing.append(f"- {c['case_no']} | {name}\n  {(c.get('full_text', '') or '')[:300]}")
    prompt = (
        f"도로교통법 제{jo}조({jo_title})의 핵심 주제와 **직접 관련된** 판례만 골라라.\n"
        f"다른 조문 위반이 본질인 사건이거나 제{jo}조를 스쳐 언급한 정도면 제외한다.\n\n"
        f"[조문 해설 요지]\n{(resources.get('law_comment') or '')[:400]}\n\n"
        f"[후보 판례]\n" + '\n\n'.join(listing) +
        '\n\n[출력 — JSON만] {"relevant": ["사건번호", ...], "reason": "근거 한 줄"}'
    )
    resp = call_gemini_api(prompt, temperature=0.0)
    keep = None
    if resp:
        try:
            parsed = json.loads(_strip_codeblock(resp))
        except json.JSONDecodeError:
            parsed = None
        # 응답이 dict({"relevant":[...]})·list([...]) 둘 다 허용 (bare 배열 시 크래시 방지)
        rel = (parsed.get('relevant') if isinstance(parsed, dict)
               else parsed if isinstance(parsed, list) else None)
        if isinstance(rel, list):
            keep = {str(x).strip() for x in rel}
    if keep is None:  # LLM 실패·파싱오류 — 코드 점수 상위로 fallback
        print("    ⚠️ 관련성 필터 실패 — 코드 점수 상위로 fallback")
        admin = sorted(resources['admin_cases'],
                       key=lambda c: -_case_relevance_score(jo, jo_title, c))[:MAX_ADMIN_CASES]
        court = sorted(resources['court_cases'],
                       key=lambda c: -_case_relevance_score(jo, jo_title, c))[:MAX_COURT_CASES]
        return {**resources, 'admin_cases': admin, 'court_cases': court}
    # 관련 판례 중 코드 점수 상위로 최종 카드 노출 수만큼만
    admin = sorted([c for c in resources['admin_cases'] if c['case_no'] in keep],
                   key=lambda c: -_case_relevance_score(jo, jo_title, c))[:MAX_ADMIN_CASES]
    court = sorted([c for c in resources['court_cases'] if c['case_no'] in keep],
                   key=lambda c: -_case_relevance_score(jo, jo_title, c))[:MAX_COURT_CASES]
    print(f"    🔎 관련성 필터: 후보 {len(cases)}건 → {len(admin) + len(court)}건")
    return {**resources, 'admin_cases': admin, 'court_cases': court}


def build_card(selection, indexes, use_llm=True):
    jo = selection['jo']
    jo_entry = indexes['law'].get(jo)
    jo_title = jo_entry.get('title', '') if isinstance(jo_entry, dict) else ''

    version, changed = find_recent_revision(jo, indexes['revisions'])
    resources = find_resources(jo, indexes, selection['basis'].get('category'), jo_title)

    # R9-5: 관련성 사전 필터 — 조문과 직접 관련된 판례만 남김
    orig_count = len(resources['admin_cases']) + len(resources['court_cases'])
    if use_llm and GEMINI_API_KEY:
        resources = filter_relevant_cases(jo, jo_title, resources)

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
            'article_text': indexes['law_articles'].get(jo, ''),  # 현행 조문 원문 (R8 D1)
            'resources_found': {
                'has_law_comment': resources['law_comment'] is not None,
                'admin_cases_count': len(resources['admin_cases']),
                'court_cases_count': len(resources['court_cases']),
                'candidates_before_filter': orig_count,
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

    # R5.5/R7-4: 자료 출처 가시화 — 해설집·실무자료 전문을 카드에 기록.
    # UI는 미리보기 + 접기/펼치기로 전체 노출. 길이는 인덱스 단계에서 이미 한정됨.
    card['source_materials'] = {
        'law_comment': resources['law_comment'] or None,
        'topic_docs': [
            {
                'doc_id': t.get('doc_id', ''),
                'title': t.get('title', ''),
                'excerpt': t.get('content', '') or '',
            }
            for t in resources.get('topic_docs', [])
        ],
    }

    if use_llm:
        enrich_card(card, jo, jo_title, version, resources)
        if card.get('llm_status') == 'ok':
            inject_history_notes(card, jo, resources, indexes['law_history'])
    else:
        card['llm_status'] = 'skipped_by_flag'

    return card


def build_daily(target_date, indexes, schedule, use_llm=True):
    base = {
        'date': target_date.strftime('%Y-%m-%d'),
        'generated_at': datetime.now().isoformat(),
        'milestone': 'M2.6',
        'version': 5,
    }
    # A4: 주말(토·일)은 카드 생성 안 함 — 주말엔 휴식
    if target_date.weekday() >= 5:
        base['status'] = 'weekend'
        return base
    if not indexes['articles']:
        base['status'] = 'skip'
        base['reason'] = 'index_articles.json 없음'
        return base

    selection = select_card_for_date(indexes['articles'], target_date, schedule)
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
    schedule = load_schedule()
    print(f"📚 인덱스: 해설 {len(indexes['law'])} · 행정심판 {len(indexes['cases'])} · "
          f"대법원 {len(indexes['court_index'])} · 후보풀 {len(indexes['articles'])}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    # 카드 간 간격 (분당 한도 429 회피) — 실제 카드 생성 사이에만 대기. --no-llm은 대기 없음.
    gap = 25 if (args.days > 1 and not args.no_llm) else 0
    results = []
    last_was_card = False
    for d in range(args.days):
        target = start_date + timedelta(days=d)
        if last_was_card and gap:
            print(f"  ⏳ 분당 한도 회피 — {gap}초 대기")
            time.sleep(gap)
        content = build_daily(target, indexes, schedule, use_llm=not args.no_llm)
        results.append((target, content))

        if content.get('status') == 'weekend':
            print(f"  🌴 {target.strftime('%Y-%m-%d')} 주말 — 카드 생성 안 함")
            last_was_card = False
            continue
        last_was_card = True
        if not args.dry_run:
            out = OUTPUT_DIR / f"daily_{target.strftime('%Y-%m-%d')}.json"
            with open(out, 'w', encoding='utf-8') as f:
                json.dump(content, f, ensure_ascii=False, indent=2)
            size_kb = out.stat().st_size / 1024
            print(f"  💾 {out.name} ({size_kb:.0f}KB)")
    if not args.dry_run:
        save_schedule(schedule)

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
