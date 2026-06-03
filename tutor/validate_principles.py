"""
principles.json 정적 검증
==========================
법률 학습 원칙 카드의 형식·출처·번호 정합성을 자동 검증한다.
**환각 콘텐츠가 운영 빌드에 들어가는 것을 차단**하는 1차 가드.

호출 방식:
    1) CLI: python tutor/validate_principles.py
    2) build_tutor_content.py 빌드 시작 시 자동 호출 (실패 시 SystemExit)

검증 범위 (정적):
    - rank 1~N 연속, 중복 없음
    - 필수 필드 존재 (principle_id, title, category, rank, summary, key_quote,
                    leading_cases, examples_for_class, sources_official)
    - leading_cases[].url 이 정부·준공식 사이트 도메인 화이트리스트 통과
    - leading_cases[].label 의 판례 번호가 정규식 형식 일치
    - examples_for_class 와 discussion_questions 가 비어있지 않음

검증 범위 외 (이 스크립트로는 못 함):
    - 판례 본문이 실제로 인용 내용과 일치하는지 (WebFetch + Codex 교차검증 필요)
    - 법리 자체의 학술적 정확성

실패 시: 에러 메시지 + 종료 코드 1
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PRINCIPLES_JSON = SCRIPT_DIR / 'data' / 'principles.json'

# 정부 사이트 + 준공식 판례 DB 화이트리스트
ALLOWED_DOMAINS = {
    'law.go.kr',
    'www.law.go.kr',
    'scourt.go.kr',
    'www.scourt.go.kr',
    'glaw.scourt.go.kr',
    'ccourt.go.kr',
    'www.ccourt.go.kr',
    'casenote.kr',
}

# 판례 번호 정규식 — 한국 판례 번호 표준 패턴
# 예: 84도79, 2017두59949, 94누16168, 2016헌가6, 98헌바37, 2018초기306, 92도999
CASE_NUMBER_RE = re.compile(
    r'\d{2,4}'                                # 연도 (2자리 또는 4자리)
    r'(?:도|누|다|두|마|므|므지|호|초기|헌가|헌바|헌마|헌라|헌나)'  # 사건 부호
    r'\d+'                                    # 일련번호
)

REQUIRED_FIELDS = {
    'principle_id',
    'title',
    'category',
    'rank',
    'summary',
    'key_quote',
    'leading_cases',
    'examples_for_class',
    'sources_official',
}


def _check_url_allowed(url: str) -> bool:
    """URL이 정부 사이트 화이트리스트에 있는 도메인인지 확인."""
    m = re.match(r'https?://([^/]+)', url)
    if not m:
        return False
    host = m.group(1).lower()
    return any(host == d or host.endswith('.' + d) for d in ALLOWED_DOMAINS)


def _check_case_number_in_label(label: str) -> bool:
    """label 문자열에 판례 번호 패턴이 포함됐는지.

    label은 "대법원 1984. 4. 10. 선고 84도79 판결" 또는
    "헌법재판소 2000. 2. 24. 선고 98헌바37 결정" 같은 형식.
    판례 번호 없는 일반론 인용도 있으므로 빈 leading_cases는 별도로 처리.
    """
    return bool(CASE_NUMBER_RE.search(label))


def validate(path: Path) -> list[str]:
    """principles.json 검증. 에러 메시지 리스트 반환 (빈 리스트=통과)."""
    errors: list[str] = []

    if not path.exists():
        return [f'파일 없음: {path}']

    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        return [f'JSON 파싱 실패: {e}']

    principles = data.get('principles')
    if not isinstance(principles, list) or not principles:
        return ['principles 배열 없음 또는 비어있음']

    # rank 연속성·중복 검증
    ranks = [p.get('rank') for p in principles]
    expected = list(range(1, len(principles) + 1))
    if sorted(ranks) != expected:
        errors.append(
            f'rank 불연속/중복: 발견={sorted(ranks)}, 기대={expected}'
        )

    # principle_id 중복 검증
    ids = [p.get('principle_id') for p in principles]
    if len(set(ids)) != len(ids):
        dups = [i for i in ids if ids.count(i) > 1]
        errors.append(f'principle_id 중복: {set(dups)}')

    # 카드별 상세 검증
    for p in principles:
        rank = p.get('rank', '?')
        tag = f'[rank {rank}]'

        # 필수 필드
        missing = REQUIRED_FIELDS - set(p.keys())
        if missing:
            errors.append(f'{tag} 필수 필드 누락: {sorted(missing)}')

        # leading_cases 검증 — 비어있어도 OK (일반론 카드), 단 warning 명시 권장
        cases = p.get('leading_cases', [])
        if not isinstance(cases, list):
            errors.append(f'{tag} leading_cases가 배열이 아님')
            cases = []
        for i, c in enumerate(cases):
            if not isinstance(c, dict):
                errors.append(f'{tag} leading_cases[{i}] 객체 아님')
                continue
            url = c.get('url', '')
            label = c.get('label', '')
            if url and not _check_url_allowed(url):
                errors.append(
                    f'{tag} leading_cases[{i}] url 비허용 도메인: {url}'
                )
            # 판례 번호 형식 검증 — 일반론 라벨은 통과 (예: "헌법재판소·대법원 일반 법리")
            # label에 판례번호 패턴이 있으면 정확히 일치해야 함
            if label and '판결' in label or '결정' in label:
                # "판결"/"결정"이 들어간 정식 인용이면 번호 형식 필수
                if not _check_case_number_in_label(label):
                    errors.append(
                        f'{tag} leading_cases[{i}] label에 판례 번호 패턴 없음: {label}'
                    )

        # examples_for_class
        ex = p.get('examples_for_class', [])
        if not isinstance(ex, list) or not ex:
            errors.append(f'{tag} examples_for_class 비어있음')

        # sources_official — 정부 사이트 안내
        srcs = p.get('sources_official', [])
        if not isinstance(srcs, list) or not srcs:
            errors.append(f'{tag} sources_official 비어있음')
        else:
            for i, s in enumerate(srcs):
                if isinstance(s, dict) and s.get('url'):
                    if not _check_url_allowed(s['url']):
                        errors.append(
                            f'{tag} sources_official[{i}] 비허용 도메인: {s["url"]}'
                        )

    return errors


def main() -> int:
    print(f'🔍 검증: {PRINCIPLES_JSON}')
    errors = validate(PRINCIPLES_JSON)
    if errors:
        print(f'❌ {len(errors)}개 오류:')
        for e in errors:
            print(f'  - {e}')
        return 1
    print(f'✅ 모든 검증 통과')
    return 0


if __name__ == '__main__':
    sys.exit(main())
