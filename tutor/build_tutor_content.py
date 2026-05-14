"""
출근길 법령 튜터 — 일일 학습 콘텐츠 생성 (M2.5: 해설·판례 통합 RAG)
=====================================================
입력:
  - ../alarm/data/recent_revisions.json   개정 법령 (필수)
  - ./data/index_law_comment.json         조문 → 해설집 청크 (있으면 보강)
  - ./data/index_cases.json               조문 → 관련 판례 case_no 리스트
  - ./data/cases_excerpts.json            case_no → 발췌 (RAG 입력용)

출력: ./data/daily_YYYY-MM-DD.json

확장된 RAG 알고리즘:
  1. 후보 조문 선정 (M1·M2와 동일, 결정론적 회전)
  2. 매핑법률조문에 대해 인덱스에서 해설·판례 수집 (최대 3건 판례)
  3. 통합 컨텍스트(개정 + 해설 + 판례)로 Gemini 호출
  4. 출력 필드 확장: oneliner, explanation, related_cases[], key_issues[], study_points[]
  5. 코드 자기검증 강화:
     - 인용한 case_no가 자료에 실제 존재하는지 확인 (할루시네이션 차단)
     - 매핑조문번호 일치, 필드 비어있지 않음, 길이 한도

격리 원칙:
  - 입력: alarm/data + tutor/data (인덱스) — 읽기만
  - 출력: tutor/data/daily_*.json
  - 인덱스 없으면(M2 환경) 자동 fallback — 해설·판례 없이 동작
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
INPUT_PATH = SCRIPT_DIR.parent / 'alarm' / 'data' / 'recent_revisions.json'
OUTPUT_DIR = SCRIPT_DIR / 'data'

# M2.5: 인덱스 파일 (없으면 자동 fallback)
INDEX_LAW_PATH = OUTPUT_DIR / 'index_law_comment.json'
INDEX_CASES_PATH = OUTPUT_DIR / 'index_cases.json'
CASES_EXCERPTS_PATH = OUTPUT_DIR / 'cases_excerpts.json'

WINDOW_DAYS = 90
EPOCH = datetime(2026, 1, 1)
MAX_RELATED_CASES = 3  # LLM 컨텍스트에 포함할 최대 판례 수

# Gemini API 설정
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash-lite-001').strip()
GEMINI_URL_TEMPLATE = (
    'https://generativelanguage.googleapis.com/v1beta/'
    'models/{model}:generateContent?key={key}'
)
GEMINI_TIMEOUT = 60


# ─── 데이터 로더 ────────────────────────────────────────────

def load_recent_revisions():
    if not INPUT_PATH.exists():
        print(f"❌ {INPUT_PATH} 없음 — alarm/build_alarm_data.py가 먼저 실행되어야 합니다")
        sys.exit(1)
    with open(INPUT_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_indexes():
    """해설·판례 인덱스 로드. 없으면 빈 dict 반환 (M2 동작 fallback)."""
    indexes = {'law': {}, 'cases': {}, 'excerpts': {}}
    triples = [
        ('law', INDEX_LAW_PATH, '조문별'),
        ('cases', INDEX_CASES_PATH, '조문별'),
        ('excerpts', CASES_EXCERPTS_PATH, '데이터'),
    ]
    for key, path, root_key in triples:
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            indexes[key] = data.get(root_key, {})
        else:
            print(f"  ⚠️ {path.name} 없음 — 해당 보강 비활성")
    return indexes


def collect_candidates(revisions_data, today, window_days=WINDOW_DAYS):
    """최근 N일 이내 공포 + 매핑법률조문 있는 변경조문 후보 리스트."""
    candidates = []
    cutoff = today - timedelta(days=window_days)
    for version in revisions_data.get('버전들', []):
        gp_date_str = version.get('공포일자', '')
        if not gp_date_str:
            continue
        try:
            gp_date = datetime.strptime(gp_date_str, '%Y%m%d')
        except ValueError:
            continue
        if gp_date < cutoff:
            continue
        for article in version.get('변경조문', []):
            mapped = article.get('매핑법률조문')
            if not mapped:
                continue
            candidates.append({
                'version': version,
                'article': article,
                'gp_date': gp_date,
            })
    candidates.sort(key=lambda c: c['gp_date'], reverse=True)
    return candidates


def select_today_candidate(candidates, target_date):
    if not candidates:
        return None
    days_since = (target_date - EPOCH).days
    idx = days_since % len(candidates)
    return candidates[idx]


def find_related_resources(article, indexes):
    """매핑법률조문에 대해 해설·판례 매칭.

    Returns dict: {'law_comment': str|None, 'related_cases': [{...}, ...]}
    """
    mapped_jo = article.get('매핑법률조문', '')
    if not mapped_jo:
        return {'law_comment': None, 'related_cases': []}

    law_entry = indexes['law'].get(mapped_jo)
    law_comment = law_entry.get('content') if isinstance(law_entry, dict) else None

    case_nos = indexes['cases'].get(mapped_jo, []) or []
    related_cases = []
    # 여유 두고 추출 (excerpts에 없는 case_no 스킵)
    for case_no in case_nos[:MAX_RELATED_CASES * 4]:
        excerpt = indexes['excerpts'].get(case_no)
        if not excerpt:
            continue
        related_cases.append({
            'case_no': case_no,
            'title': excerpt.get('title', ''),
            'date': excerpt.get('date', ''),
            'court': excerpt.get('court', ''),
            'result': excerpt.get('result', ''),
            'reasoning_excerpt': (excerpt.get('reasoning_excerpt') or '')[:600],
        })
        if len(related_cases) >= MAX_RELATED_CASES:
            break

    return {'law_comment': law_comment, 'related_cases': related_cases}


# ─── Gemini API 호출 계층 (M2와 동일, maxOutputTokens 확장) ─────────────────────────────────────

def call_gemini_api(prompt, temperature=0.3, timeout=GEMINI_TIMEOUT,
                    max_retries=3, backoff_seconds=(20, 60, 120)):
    """Gemini REST API 단일 호출 + 429/5xx 자동 재시도."""
    if not GEMINI_API_KEY:
        return None
    url = GEMINI_URL_TEMPLATE.format(model=GEMINI_MODEL, key=GEMINI_API_KEY)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 3072,  # M2.5: 풍부한 출력 위해 확장
        },
    }
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(url, json=body, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get('candidates', [])
            if not candidates:
                return None
            first = candidates[0]
            finish_reason = first.get('finishReason', '')
            if finish_reason and finish_reason not in ('STOP', 'FINISH_REASON_STOP'):
                print(f"  ⚠️ Gemini finishReason={finish_reason} (응답 미완료 가능)")
            parts = first.get('content', {}).get('parts', [])
            if not parts:
                return None
            return parts[0].get('text', '').strip()
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            retryable = status == 429 or 500 <= status < 600
            if retryable and attempt < max_retries:
                wait = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                print(f"  ⏳ Rate limit/서버 오류 (status={status}) — {wait}초 후 재시도 ({attempt + 1}/{max_retries + 1})")
                time.sleep(wait)
                continue
            print(f"  ⚠️ Gemini 호출 최종 실패 (status={status})")
            if e.response is not None:
                try:
                    print(f"  응답 본문: {e.response.text[:300]}")
                except Exception:
                    pass
            return None
        except requests.RequestException as e:
            print(f"  ⚠️ Gemini 호출 네트워크 오류: {type(e).__name__} — {e}")
            return None
        except (KeyError, IndexError, ValueError) as e:
            print(f"  ⚠️ Gemini 응답 파싱 실패: {type(e).__name__} — {e}")
            return None
    return None


def _strip_markdown_codeblock(text):
    return re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip(), flags=re.MULTILINE).strip()


def _build_context_block(version, article, resources):
    """RAG 컨텍스트 — 개정 + 해설(있을 때) + 판례 N건(있을 때).

    LLM이 컨텍스트 안에서만 작성하도록 강제하는 핵심 가드레일.
    """
    parts = [
        f"""[원본 자료 1: 개정 법령 정보]
법령명: {version.get('법령명', '')}
법령유형: {version.get('법령유형', '')}
공포일자: {version.get('공포일자', '')}
시행일자: {version.get('시행일자', '')}
제개정구분: {version.get('제개정구분', '')}
변경 조문: 제{article.get('조문번호', '')}조 {article.get('조문제목', '')}
매핑된 법률 조문: 제{article.get('매핑법률조문', '')}조 {article.get('매핑법률조문제목', '')}

[제개정 이유 원문]
{version.get('제개정이유', '').strip()}
"""
    ]

    if resources['law_comment']:
        parts.append(f"""[원본 자료 2: 도로교통법 해설 — 제{article.get('매핑법률조문', '')}조]
{resources['law_comment']}
""")

    if resources['related_cases']:
        case_blocks = []
        for c in resources['related_cases']:
            case_blocks.append(
                f"- 사건번호: {c['case_no']}\n"
                f"  제목: {c['title']}\n"
                f"  법원·일자: {c['court']} ({c['date']})\n"
                f"  결과: {c['result']}\n"
                f"  이유 발췌: {c['reasoning_excerpt']}"
            )
        parts.append(
            f"[원본 자료 3: 관련 행정심판례 ({len(resources['related_cases'])}건)]\n"
            + '\n\n'.join(case_blocks)
            + '\n'
        )

    return '\n'.join(parts)


def generate_learning_content(version, article, resources):
    """1차 호출 — 통합 RAG 가드레일 프롬프트로 풍부한 학습 콘텐츠 생성."""
    context = _build_context_block(version, article, resources)
    mapped_jo = article.get('매핑법률조문', '')

    prompt = f"""당신은 한국 교통법규 학습 콘텐츠 작성자입니다.

다음 "원본 자료"에 있는 내용만 사용하여 학습 콘텐츠를 작성하세요.

**규칙 (반드시 지킬 것)**:
1. 원본 자료에 없는 정보(다른 조문·다른 사건·추가 사례·개인 의견·인터넷 지식)는 절대 추가 금지
2. 인용한 사건번호(case_no)는 반드시 [원본 자료 3]에 명시된 것만 사용 — 새로 만들어내면 안 됨
3. source_article 필드는 반드시 "도로교통법 제{mapped_jo}조"와 일치
4. 자료가 부족하다고 판단되면 status를 "skip"으로 반환

{context}

[출력 형식 — 아래 JSON만 출력. 마크다운 코드블록(```)·설명·접두사 X]
{{
  "status": "ok",
  "oneliner": "한 줄 법령 요약 (50자 이내, 핵심 변화 또는 핵심 의무)",
  "explanation": "30초 해설 (150자 이내, 무엇이 바뀌었거나 핵심 내용 + 왜 중요한지)",
  "source_article": "도로교통법 제{mapped_jo}조",
  "related_cases": [
    {{"case_no": "위 자료의 사건번호", "title": "사건 제목 요약", "result": "인용/기각/각하", "lesson": "이 사건의 학습 포인트 1줄 (50자 이내)"}}
  ],
  "key_issues": [
    "이 조문 관련 핵심 쟁점 1 (60자 이내)",
    "이 조문 관련 핵심 쟁점 2 (60자 이내)"
  ],
  "study_points": [
    "교수 강의 관점 학습 포인트 1 (80자 이내)",
    "교수 강의 관점 학습 포인트 2 (80자 이내)"
  ]
}}

조건부 필드 규칙:
- related_cases: [원본 자료 3]이 있으면 최대 {MAX_RELATED_CASES}건. 없으면 빈 배열 [].
- key_issues: 자료에서 도출 가능한 쟁점 2~3개. 추측·확장 금지.
- study_points: 교수 학습 관점의 핵심 메시지 2~3개. 자료 밖 의견 금지.

자료 부족 시:
{{"status": "skip", "reason": "구체적 이유"}}
"""
    response = call_gemini_api(prompt, temperature=0.3)
    if response is None:
        return None
    cleaned = _strip_markdown_codeblock(response)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"  ⚠️ LLM 응답 JSON 파싱 실패: {e}")
        print(f"  raw 미리보기: {response[:300]}...")
        return None


def verify_content(generated, version, article, resources):
    """결정론적 코드 자기검증 (M2.5 강화).

    추가 검증:
      - 인용된 case_no가 [원본 자료 3]에 실제 존재 (할루시네이션 차단)
      - related_cases·key_issues·study_points 타입·길이 검증
    """
    if generated is None or generated.get('status') != 'ok':
        return 'SKIP_NO_CONTENT'

    mapped_jo = article.get('매핑법률조문', '')
    expected_jo_substr = f'제{mapped_jo}조'

    # 1. 필수 필드 (M2와 동일)
    for field in ('oneliner', 'explanation', 'source_article'):
        value = generated.get(field, '')
        if not isinstance(value, str) or not value.strip():
            return f'FAIL_field_empty:{field}'

    # 2. source_article 매핑 조문 포함
    if expected_jo_substr not in generated['source_article']:
        return (f'FAIL_source_article_missing_jo:'
                f'expected="{expected_jo_substr}",got="{generated["source_article"]}"')

    # 3. 길이 한도 (M2와 동일)
    if len(generated['oneliner']) > 80:
        return f'FAIL_oneliner_too_long:{len(generated["oneliner"])}자'
    if len(generated['explanation']) > 250:
        return f'FAIL_explanation_too_long:{len(generated["explanation"])}자'

    # 4. M2.5 강화: 인용된 case_no가 자료에 실제 있는지 확인
    allowed_case_nos = {c['case_no'] for c in resources['related_cases']}
    related_cases = generated.get('related_cases', [])
    if not isinstance(related_cases, list):
        return 'FAIL_related_cases_not_list'
    for i, case in enumerate(related_cases):
        if not isinstance(case, dict):
            return f'FAIL_related_case_not_dict:idx={i}'
        case_no = case.get('case_no', '')
        if case_no and case_no not in allowed_case_nos:
            return f'FAIL_invented_case_no:{case_no} (not in source materials)'
        if case_no:
            for sub in ('title', 'result', 'lesson'):
                if not case.get(sub, '').strip():
                    return f'FAIL_case_field_empty:idx={i},field={sub}'

    # 5. key_issues / study_points 검증
    for list_field in ('key_issues', 'study_points'):
        items = generated.get(list_field, [])
        if not isinstance(items, list):
            return f'FAIL_{list_field}_not_list'
        for j, it in enumerate(items):
            if not isinstance(it, str) or not it.strip():
                return f'FAIL_{list_field}_invalid:idx={j}'
            if len(it) > 120:
                return f'FAIL_{list_field}_too_long:idx={j},len={len(it)}'

    return 'PASS'


def enrich_with_llm(content, version, article, resources):
    """build_daily_content 결과에 LLM 생성 필드 추가."""
    if not GEMINI_API_KEY:
        content['llm_status'] = 'skip_no_api_key'
        content['llm_note'] = 'GEMINI_API_KEY 환경변수 미설정 — 기본 정보만 출력'
        return content

    print(f"\n🤖 LLM 1차 생성 호출 (model={GEMINI_MODEL})")
    print(f"   컨텍스트 구성: 개정 + 해설 {'✓' if resources['law_comment'] else '✗'} + 판례 {len(resources['related_cases'])}건")

    generated = generate_learning_content(version, article, resources)

    if generated is None:
        content['llm_status'] = 'skip_call_failed'
        content['llm_note'] = 'LLM 호출 또는 응답 파싱 실패'
        return content

    if generated.get('status') != 'ok':
        content['llm_status'] = 'skip_llm_returned_skip'
        content['llm_note'] = f"LLM 자체 SKIP — {generated.get('reason', '')}"
        return content

    print(f"  ✅ 1차 생성 완료")
    print(f"  🔍 코드 자기검증 (case_no·필드·길이 검증)")
    verdict = verify_content(generated, version, article, resources)

    if verdict != 'PASS':
        content['llm_status'] = 'skip_verification_failed'
        content['llm_note'] = f'자기검증 FAIL — {verdict}'
        content['llm_draft'] = generated
        print(f"  ❌ 자기검증 실패: {verdict}")
        return content

    print(f"  ✅ 자기검증 PASS")
    content['candidate']['oneliner'] = generated.get('oneliner', '')
    content['candidate']['explanation'] = generated.get('explanation', '')
    content['candidate']['source_article'] = generated.get('source_article', '')
    content['candidate']['related_cases'] = generated.get('related_cases', [])
    content['candidate']['key_issues'] = generated.get('key_issues', [])
    content['candidate']['study_points'] = generated.get('study_points', [])
    content['llm_status'] = 'ok'
    return content


# ─── 메인 빌드 함수 ────────────────────────────────────────────

def build_daily_content(target_date, candidate, indexes, use_llm=True):
    base = {
        'date': target_date.strftime('%Y-%m-%d'),
        'generated_at': datetime.now().isoformat(),
        'milestone': 'M2.5',
        'version': 3,
    }

    if candidate is None:
        base.update({
            'status': 'skip',
            'reason': f'학습 후보 없음 (최근 {WINDOW_DAYS}일 이내 매핑된 변경 조문 없음)',
        })
        return base

    version = candidate['version']
    article = candidate['article']
    mapped_jo = article.get('매핑법률조문', '')

    resources = find_related_resources(article, indexes)

    base.update({
        'status': 'ok',
        'candidate': {
            '법령유형': version.get('법령유형'),
            '법령명': version.get('법령명'),
            '공포일자': version.get('공포일자'),
            '시행일자': version.get('시행일자'),
            '제개정구분': version.get('제개정구분'),
            '제개정이유_원본': version.get('제개정이유', '').strip(),
            '조문': {
                '조문번호': article.get('조문번호'),
                '조문제목': article.get('조문제목'),
                '매핑법률조문': mapped_jo,
                '매핑법률조문제목': article.get('매핑법률조문제목', ''),
                '조문시행일자': article.get('조문시행일자', ''),
                '조문제개정유형': article.get('조문제개정유형', ''),
            },
            'viewer_link': f'../viewer.html?jo={mapped_jo}',
            'resources_found': {
                'has_law_comment': resources['law_comment'] is not None,
                'related_cases_count': len(resources['related_cases']),
            },
        },
    })

    if use_llm:
        enrich_with_llm(base, version, article, resources)
    else:
        base['llm_status'] = 'skipped_by_flag'
        base['llm_note'] = '--no-llm 옵션 사용 — 기본 정보만 출력'

    return base


def main():
    sys.stdout.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(description='일일 법령 학습 콘텐츠 생성 (M2.5)')
    parser.add_argument('--dry-run', action='store_true', help='파일 저장 없이 stdout 출력만')
    parser.add_argument('--date', type=str, default=None, help='대상 날짜 (YYYY-MM-DD)')
    parser.add_argument('--no-llm', action='store_true', help='LLM 호출 건너뛰기')
    args = parser.parse_args()

    if args.date:
        try:
            target_date = datetime.strptime(args.date, '%Y-%m-%d')
        except ValueError:
            print(f"❌ --date 형식 오류: '{args.date}'")
            sys.exit(1)
    else:
        target_date = datetime.now()

    print("=" * 60)
    print(f"  📚 일일 법령 학습 콘텐츠 생성 (M2.5) — {target_date.strftime('%Y-%m-%d')}")
    print("=" * 60)

    if args.no_llm:
        print("⏭️ --no-llm 옵션 — LLM 단계 건너뜀")
    elif GEMINI_API_KEY:
        print(f"🔑 GEMINI_API_KEY 감지 (model={GEMINI_MODEL})")
    else:
        print("⚠️ GEMINI_API_KEY 없음 — 기본 정보만 출력")

    revisions = load_recent_revisions()
    print(f"📖 개정 입력: 버전수 {revisions.get('버전수', 0)}")

    indexes = load_indexes()
    print(f"📚 인덱스: 해설 {len(indexes['law'])} 조문, 판례 매핑 {len(indexes['cases'])} 조문, 발췌 {len(indexes['excerpts'])} 건")

    candidates = collect_candidates(revisions, target_date)
    print(f"\n🔍 후보 추출: 최근 {WINDOW_DAYS}일 + 매핑법률조문 있음 → {len(candidates)}건")

    selected = select_today_candidate(candidates, target_date)
    if selected:
        v = selected['version']
        a = selected['article']
        days_since = (target_date - EPOCH).days
        idx = days_since % len(candidates)
        print(f"\n✅ 선택 (idx={idx}/{len(candidates) - 1}):")
        print(f"  법령: {v['법령명']} · {v['법령유형']}")
        print(f"  변경조문: 제{a['조문번호']}조 {a['조문제목']}")
        print(f"  매핑법률: 제{a['매핑법률조문']}조 {a['매핑법률조문제목']}")
    else:
        print(f"\n⚠️ 후보 없음 → SKIP")

    content = build_daily_content(target_date, selected, indexes, use_llm=not args.no_llm)

    if 'llm_status' in content:
        print(f"\n📊 LLM 상태: {content['llm_status']}")
        if content['llm_status'] == 'ok':
            c = content['candidate']
            print(f"  oneliner: {c.get('oneliner', '')}")
            print(f"  관련 판례: {len(c.get('related_cases', []))} 건")
            for cs in c.get('related_cases', []):
                print(f"    · {cs.get('case_no', '?')} — {cs.get('result', '?')} — {cs.get('lesson', '')[:50]}")
            print(f"  핵심 쟁점: {len(c.get('key_issues', []))} 개")
            for it in c.get('key_issues', []):
                print(f"    · {it}")
            print(f"  학습 포인트: {len(c.get('study_points', []))} 개")
            for it in c.get('study_points', []):
                print(f"    · {it}")

    if args.dry_run:
        print(f"\n📋 --dry-run: 파일 미저장, JSON 출력:")
        print("-" * 60)
        print(json.dumps(content, ensure_ascii=False, indent=2))
        return

    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / f"daily_{target_date.strftime('%Y-%m-%d')}.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(content, f, ensure_ascii=False, indent=2)

    size_kb = output_path.stat().st_size / 1024
    print(f"\n💾 저장: {output_path} ({size_kb:.1f}KB)")


if __name__ == '__main__':
    main()
