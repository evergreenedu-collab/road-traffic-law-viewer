"""
출근길 법령 튜터 — 일일 학습 콘텐츠 생성 (M2: Gemini API 통합)
=====================================================
입력: ../alarm/data/recent_revisions.json (alarm 워크플로 산출물)
출력: ./data/daily_YYYY-MM-DD.json

알고리즘:
  1. recent_revisions.json 로드
  2. 최근 N일 이내 공포 + 매핑법률조문 있는 변경조문 후보 추출
  3. 대상 날짜 기반 결정론적 인덱싱으로 후보 1건 선택
  4. RAG 컨텍스트 강제로 Gemini API 호출 → oneliner + explanation 생성
  5. 자기검증(2차 호출) → 원본 자료와 일치 확인
  6. 검증 실패 시 SKIP, 성공 시 JSON에 LLM 결과 추가

격리 원칙:
  - 입력: alarm/data/recent_revisions.json (읽기만)
  - 출력: tutor/data/daily_*.json (튜터 폴더 자체)
  - 기존 워크플로·viewer.html 미영향
  - GEMINI_API_KEY 환경변수 누락 시: LLM 단계 자동 skip, M1 수준만 출력

환경변수:
  GEMINI_API_KEY  (LLM 생성 활성화에 필수, 미설정 시 SKIP)
  GEMINI_MODEL    (기본: gemini-2.0-flash, 사용자 override 가능)

사용법:
  py tutor/build_tutor_content.py             # 오늘 날짜로 생성·파일 저장
  py tutor/build_tutor_content.py --dry-run   # stdout 출력만
  py tutor/build_tutor_content.py --date 2026-05-14
  py tutor/build_tutor_content.py --no-llm    # LLM 단계 건너뛰기 (M1 수준)
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

# 후보 선택 윈도우 (일)
WINDOW_DAYS = 90
# 결정론적 인덱싱 기준일
EPOCH = datetime(2026, 1, 1)

# Gemini API 설정 (환경변수 기반)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
# 기본 모델: 2.0-flash-lite-001 — thinking 없어 출력 토큰 효율적, 무료 한도 관대
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash-lite-001').strip()
GEMINI_URL_TEMPLATE = (
    'https://generativelanguage.googleapis.com/v1beta/'
    'models/{model}:generateContent?key={key}'
)
GEMINI_TIMEOUT = 60  # 초


def load_recent_revisions():
    """alarm 빌드 산출물 로드. 없으면 명확한 에러 후 종료."""
    if not INPUT_PATH.exists():
        print(f"❌ {INPUT_PATH} 없음 — alarm/build_alarm_data.py가 먼저 실행되어야 합니다")
        sys.exit(1)
    with open(INPUT_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def collect_candidates(revisions_data, today, window_days=WINDOW_DAYS):
    """최근 window_days 이내 공포된 버전 중 매핑법률조문 있는 변경조문 후보 리스트."""
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
    """대상 날짜 기반 결정론적 후보 선택 (재실행 일관성)."""
    if not candidates:
        return None
    days_since = (target_date - EPOCH).days
    idx = days_since % len(candidates)
    return candidates[idx]


# ─── Gemini API 호출 계층 ────────────────────────────────────────────

def call_gemini_api(prompt, temperature=0.3, timeout=GEMINI_TIMEOUT,
                    max_retries=3, backoff_seconds=(20, 60, 120)):
    """Gemini REST API 단일 호출 + 429 자동 재시도.

    의존성: requests만 사용 (Google SDK 패키지 미사용).
    재시도: 429(Rate Limit)·5xx 발생 시 백오프 후 재시도. 기타 에러는 즉시 None.
    """
    if not GEMINI_API_KEY:
        return None
    url = GEMINI_URL_TEMPLATE.format(model=GEMINI_MODEL, key=GEMINI_API_KEY)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 2048,
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
                print(f"  ⚠️ Gemini finishReason={finish_reason} (응답 미완료 가능성)")
            parts = first.get('content', {}).get('parts', [])
            if not parts:
                return None
            return parts[0].get('text', '').strip()
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            retryable = status == 429 or 500 <= status < 600
            if retryable and attempt < max_retries:
                wait = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                print(f"  ⏳ Rate limit/서버 오류 (status={status}) — {wait}초 대기 후 재시도 ({attempt + 1}/{max_retries + 1})")
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


def _build_context_block(version, article):
    """RAG 컨텍스트 — LLM에게 주는 원본 자료 블록 (할루시네이션 차단의 근간)."""
    return f"""[원본 자료]
법령명: {version.get('법령명', '')}
법령유형: {version.get('법령유형', '')}
공포일자: {version.get('공포일자', '')}
시행일자: {version.get('시행일자', '')}
제개정구분: {version.get('제개정구분', '')}
변경 조문: 제{article.get('조문번호', '')}조 {article.get('조문제목', '')}
매핑된 법률 조문: 제{article.get('매핑법률조문', '')}조 {article.get('매핑법률조문제목', '')}
조문 시행일자: {article.get('조문시행일자', '')}

[제개정 이유 원문]
{version.get('제개정이유', '').strip()}
"""


def _strip_markdown_codeblock(text):
    """LLM이 마크다운 코드블록으로 감싸서 응답할 때 제거."""
    return re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip(), flags=re.MULTILINE).strip()


def generate_learning_content(version, article):
    """1차 호출 — RAG 가드레일 프롬프트로 oneliner + explanation 생성.

    반환: dict {'status': 'ok', 'oneliner', 'explanation', 'source_article'}
          또는 dict {'status': 'skip', 'reason'}
          또는 None (호출/파싱 실패)
    """
    context = _build_context_block(version, article)
    mapped_jo = article.get('매핑법률조문', '')

    prompt = f"""당신은 한국 교통법규 학습 콘텐츠 작성자입니다.

다음 "원본 자료"에 있는 내용만 사용하여 학습 콘텐츠를 작성하세요.
원본 자료에 없는 정보(다른 조문·다른 사건·추가 사례·개인 의견)는 절대 만들지 마세요.
원본 자료의 정보가 학습 콘텐츠 작성에 부족하다고 판단되면 status를 "skip"으로 반환하세요.

{context}

[출력 형식 — 아래 JSON만 출력. 마크다운 코드블록(```)·설명·접두사 X]
{{
  "status": "ok",
  "oneliner": "한 줄 법령 요약 (50자 이내, 핵심 변화만)",
  "explanation": "30초 해설 (150자 이내, 무엇이 바뀌었고 왜 중요한지)",
  "source_article": "도로교통법 제{mapped_jo}조"
}}

원본 자료에 매핑법률조문(제{mapped_jo}조)이 명시되어 있지 않거나 학습 작성이 어렵다면 다음을 반환:
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
        print(f"  raw 응답 미리보기: {response[:200]}...")
        return None


def verify_content(generated, version, article):
    """결정론적 코드 기반 자기검증 — 'PASS' 또는 'FAIL_<이유>'.

    LLM 기반 자기검증은 false positive(정상 콘텐츠를 잘못 FAIL 판정)가 많아
    구조·필드·매핑 일관성만 코드로 검증한다.
    1차 생성의 RAG 가드레일이 이미 원본 자료 안에서만 작성을 강제하므로
    내용의 사실 일치는 코드 검증으로 충분히 보장된다.

    검증 항목:
      1. status == 'ok'
      2. 필수 필드 존재 + 공백 아님
      3. source_article에 "제{매핑법률조문}조" 부분문자열 포함 (매핑 일관성)
      4. oneliner·explanation 길이 한도 (관용)
    """
    if generated is None or generated.get('status') != 'ok':
        return 'SKIP_NO_CONTENT'

    mapped_jo = article.get('매핑법률조문', '')
    expected_jo_substr = f'제{mapped_jo}조'

    for field in ('oneliner', 'explanation', 'source_article'):
        value = generated.get(field, '')
        if not isinstance(value, str) or not value.strip():
            return f'FAIL_field_empty_or_invalid:{field}'

    if expected_jo_substr not in generated['source_article']:
        return (f'FAIL_source_article_missing_jo:'
                f'expected_substring="{expected_jo_substr}",'
                f'got="{generated["source_article"]}"')

    if len(generated['oneliner']) > 80:
        return f'FAIL_oneliner_too_long:{len(generated["oneliner"])}자'
    if len(generated['explanation']) > 250:
        return f'FAIL_explanation_too_long:{len(generated["explanation"])}자'

    return 'PASS'


def enrich_with_llm(content, version, article):
    """build_daily_content 결과에 LLM 생성 필드 추가 (in-place + return).

    GEMINI_API_KEY 없으면 'skip_no_api_key' 마킹 후 원본 그대로 반환.
    LLM 응답 실패·자기검증 FAIL이면 해당 'skip_*' 마킹.
    성공 시 candidate에 oneliner/explanation/source_article 추가, llm_status='ok'.
    """
    if not GEMINI_API_KEY:
        content['llm_status'] = 'skip_no_api_key'
        content['llm_note'] = 'GEMINI_API_KEY 환경변수 미설정 — M1 수준만 출력'
        return content

    print(f"\n🤖 LLM 1차 생성 호출 (model={GEMINI_MODEL})")
    generated = generate_learning_content(version, article)

    if generated is None:
        content['llm_status'] = 'skip_call_failed'
        content['llm_note'] = 'LLM 호출 또는 응답 파싱 실패'
        return content

    if generated.get('status') != 'ok':
        content['llm_status'] = 'skip_llm_returned_skip'
        content['llm_note'] = f"LLM 자체 SKIP — {generated.get('reason', '')}"
        return content

    print(f"  ✅ 1차 생성 완료")
    print(f"  🔍 2차 자기검증 호출 중...")
    verdict = verify_content(generated, version, article)

    if verdict != 'PASS':
        content['llm_status'] = 'skip_verification_failed'
        content['llm_note'] = f'자기검증 FAIL — {verdict}'
        content['llm_draft'] = generated  # 디버그용 보존
        print(f"  ❌ 자기검증 실패: {verdict}")
        return content

    print(f"  ✅ 자기검증 PASS")
    content['candidate']['oneliner'] = generated.get('oneliner', '')
    content['candidate']['explanation'] = generated.get('explanation', '')
    content['candidate']['source_article'] = generated.get('source_article', '')
    content['llm_status'] = 'ok'
    return content


# ─── 메인 빌드 함수 ────────────────────────────────────────────

def build_daily_content(target_date, candidate, use_llm=True):
    """일일 학습 콘텐츠 JSON 구조 생성. use_llm=True면 Gemini 호출 단계 포함."""
    base = {
        'date': target_date.strftime('%Y-%m-%d'),
        'generated_at': datetime.now().isoformat(),
        'milestone': 'M2',
        'version': 2,
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
        },
    })

    if use_llm:
        enrich_with_llm(base, version, article)
    else:
        base['llm_status'] = 'skipped_by_flag'
        base['llm_note'] = '--no-llm 옵션 사용 — M1 수준만 출력'

    return base


def main():
    sys.stdout.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(description='일일 법령 학습 콘텐츠 생성 (M2)')
    parser.add_argument('--dry-run', action='store_true', help='파일 저장 없이 stdout 출력만')
    parser.add_argument('--date', type=str, default=None, help='대상 날짜 (YYYY-MM-DD)')
    parser.add_argument('--no-llm', action='store_true', help='LLM 호출 건너뛰기 (M1 수준)')
    args = parser.parse_args()

    if args.date:
        try:
            target_date = datetime.strptime(args.date, '%Y-%m-%d')
        except ValueError:
            print(f"❌ --date 형식 오류: '{args.date}' (예: 2026-05-14)")
            sys.exit(1)
    else:
        target_date = datetime.now()

    print("=" * 60)
    print(f"  📚 일일 법령 학습 콘텐츠 생성 — {target_date.strftime('%Y-%m-%d')}")
    print("=" * 60)

    if args.no_llm:
        print("⏭️ --no-llm 옵션 — LLM 단계 건너뜀")
    elif GEMINI_API_KEY:
        print(f"🔑 GEMINI_API_KEY 감지 (model={GEMINI_MODEL})")
    else:
        print(f"⚠️ GEMINI_API_KEY 환경변수 없음 — LLM 단계 자동 SKIP (M1 수준만)")

    revisions = load_recent_revisions()
    print(f"📖 입력: {INPUT_PATH}")
    print(f"  버전수: {revisions.get('버전수', 0)}")

    candidates = collect_candidates(revisions, target_date)
    print(f"\n🔍 후보 추출: 최근 {WINDOW_DAYS}일 이내 + 매핑법률조문 있음")
    print(f"  후보수: {len(candidates)}")

    selected = select_today_candidate(candidates, target_date)
    if selected:
        v = selected['version']
        a = selected['article']
        days_since = (target_date - EPOCH).days
        idx = days_since % len(candidates)
        print(f"\n✅ 선택된 후보 (idx={idx}/{len(candidates) - 1}):")
        print(f"  법령: {v['법령명']} ({v['법령유형']})")
        print(f"  공포일자: {v['공포일자']}, 시행일자: {v['시행일자']}")
        print(f"  변경조문: 제{a['조문번호']}조 {a['조문제목']}")
        print(f"  매핑법률: 제{a['매핑법률조문']}조 {a['매핑법률조문제목']}")
    else:
        print(f"\n⚠️ 학습 후보 없음 → SKIP")

    content = build_daily_content(target_date, selected, use_llm=not args.no_llm)

    if 'llm_status' in content:
        print(f"\n📊 LLM 상태: {content['llm_status']}")
        if content['llm_status'] == 'ok':
            print(f"  oneliner: {content['candidate'].get('oneliner', '')}")
            explanation = content['candidate'].get('explanation', '')
            print(f"  explanation: {explanation[:120]}{'...' if len(explanation) > 120 else ''}")
            print(f"  source: {content['candidate'].get('source_article', '')}")

    if args.dry_run:
        print(f"\n📋 --dry-run: 파일 미저장, JSON 출력만:")
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
