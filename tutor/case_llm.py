"""
출근길 법령 튜터 — 판례 카드 LLM 정리 (Phase 2 2b-β)
=====================================================
판례 본문(ruling/reasoning) + 페어링 조문 정보 → 6개 학습필드 자동 정리.
- oneliner: 한 줄 요약 (40~80자)
- fact_summary: 사실관계 (2~4문장)
- legal_issue: 법적 쟁점 (1~2문장, 페어링 조문과의 관련성 포함)
- conclusion: 결론·판시 (판결문 표현 그대로)
- teaching_application: 페어링 조문 학습에 주는 의미 (운전교육 일반론 금지)
- reference_digest: 판례 본문에 실제 등장한 조문·법리·연결 조문만

환경변수: GEMINI_API_KEY (필수), GEMINI_MODEL (기본 gemini-2.5-flash)

향후 2b-γ 통합 시 tutor/llm_client.py 같은 공용 모듈로 분리 권고
(현재는 build_tutor_content.py의 call_gemini_api를 복사 — 순환 의존 회피).
"""

import json
import os
import re
import time

import requests


GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash').strip()
GEMINI_URL = ('https://generativelanguage.googleapis.com/v1beta/'
              'models/{model}:generateContent?key={key}')
GEMINI_TIMEOUT = 60

# 판례 본문 LLM에 넘길 최대 길이 (긴 판례는 자름 — 시범 단계)
CASE_BODY_CHARS = 4000

REQUIRED_KEYS = [
    'oneliner', 'fact_summary', 'legal_issue',
    'conclusion', 'teaching_application', 'reference_digest',
]


# ────────────────────────────────────────────────────────────────
# Gemini 호출 (build_tutor_content.py와 동일 로직 — 2b-γ에서 공용 모듈로 분리)
# ────────────────────────────────────────────────────────────────

def call_gemini_api(prompt, temperature=0.2, timeout=GEMINI_TIMEOUT,
                    max_retries=3, backoff=(20, 60, 120)):
    if not GEMINI_API_KEY:
        return None
    url = GEMINI_URL.format(model=GEMINI_MODEL, key=GEMINI_API_KEY)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": 16384},
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


# ────────────────────────────────────────────────────────────────
# 입력 추출 (source별 필드 다름)
# ────────────────────────────────────────────────────────────────

def _extract_case_title(case_data, source):
    return case_data.get('case_name', '') if source == 'court' else case_data.get('title', '')


def _extract_case_body(case_data, source):
    if source == 'court':
        return case_data.get('ruling', '')
    return case_data.get('reasoning', '') or case_data.get('summary', '')


# ────────────────────────────────────────────────────────────────
# 프롬프트 (Codex 권고 반영)
# ────────────────────────────────────────────────────────────────

def _build_case_prompt(case_data, source, paired_jo, paired_jo_title):
    title = _extract_case_title(case_data, source)
    body = _extract_case_body(case_data, source)[:CASE_BODY_CHARS]
    court = case_data.get('court', '')
    date = case_data.get('date', '')
    case_no = case_data.get('case_no', '')
    paired_label = f"제{paired_jo}조 {paired_jo_title}".strip()

    return f"""당신은 한국도로교통공단 교수의 학습 콘텐츠 작성자입니다. 교수들이 매일 아침 읽는 자료이므로 정확성이 최우선입니다.

[학습 대상 조문 — 이 판례가 보조하는 조문]
도로교통법 {paired_label}

[작성 규칙 — 위반 시 자료 신뢰도 훼손, 반드시 지킬 것]
1. 아래 판례 본문을 '{paired_label} 학습을 설명·보충하는 사례'로만 정리한다.
   판례 자체의 일반 요약이 아니라, 왜 이 판례가 이 조문 카드에 붙는지 관점을 잡는다.
2. 판례 본문에 명시된 사실만 사용한다. 없는 수치·해석·사례는 추가하지 않는다.
3. 판례 본문에 없는 운전교육 일반론·사고예방 수칙·통계·정책적 평가는 절대 쓰지 않는다.
4. 법률 용어는 판결문·결정문 표현을 그대로 쓴다. 일상어로 의역하지 않는다.
5. '항상'·'모든 경우'·'반드시'·'예외 없이' 같은 단정·일반화는 본문이 명확히 그렇게 규정할 때만 쓴다. 불명확하면 '~될 수 있다'·'~한 경우' 등 유보적 표현을 쓴다.
6. 확실하지 않은 부분은 빈 문자열로 둔다. 추측·일반론보다 빈 채로 두는 게 낫다.

[출력 형식 — 순수 JSON 객체 1개. 마크다운 코드블럭 금지. 한국어]
{{
  "oneliner": "이 판례의 핵심을 한 줄(40~80자)로. 사건명 단순 반복 X. 마침표로 끝.",
  "fact_summary": "사실관계 요약 (2~4문장). 본문에 명시된 행위·결과·당사자만.",
  "legal_issue": "법적 쟁점 (1~2문장). {paired_label}과의 관련성을 분명히.",
  "conclusion": "결론·판시 (1~2문장). 판결문/결정문 표현 그대로.",
  "teaching_application": "이 판례가 {paired_label} 학습에 주는 의미 (2~3문장). 운전교육 일반론·사고예방 수칙 절대 금지. 판례 본문이 직접 시사하는 한도 내에서만.",
  "reference_digest": "이 판례 본문에 실제 등장한 조문·법리·연결 조문만 짧게 (1~3개 항목, 세미콜론 구분)."
}}

[판례 자료]
사건번호: {case_no}
법원: {court}
선고일: {date}
사건명: {title}

[본문]
{body}
"""


# ────────────────────────────────────────────────────────────────
# 메인: 6필드 생성
# ────────────────────────────────────────────────────────────────

def generate_case_learning_content(case_data, source, paired_jo, paired_jo_title, use_llm=True):
    """
    Returns:
      use_llm=False  → None
      성공          → {'oneliner': ..., 'fact_summary': ..., ...}  (6키 보장, str)
      LLM 실패      → None
      JSON 파싱 실패 → {'_raw': ..., '_error': 'json_parse_failed'}
    """
    if not use_llm:
        return None
    prompt = _build_case_prompt(case_data, source, paired_jo, paired_jo_title)
    raw = call_gemini_api(prompt, temperature=0.2)
    if not raw:
        return None
    cleaned = _strip_codeblock(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return {'_raw': raw, '_error': 'json_parse_failed'}

    out = {}
    for k in REQUIRED_KEYS:
        v = parsed.get(k, '')
        out[k] = str(v).strip() if v is not None else ''
    return out
