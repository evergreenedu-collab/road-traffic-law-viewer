"""
출근길 법령 튜터 — 해설집·판례 인덱스 빌더 (M2.5 Step B)
=====================================================
입력 (로컬 자산, c:\\Users\\user\\projects\\판례조회-AI도구\\):
  - 2024년 도로교통법해설.md  (경찰청 해설서, 마크다운)
  - cases.json                (2,911건 행정심판례)

출력 (tutor/data/, git commit 대상):
  - index_law_comment.json    조문번호 → {title, content} (해설 본문 청크)
  - index_cases.json          조문번호 → [case_no, ...] (조문별 판례 ID)
  - cases_excerpts.json       case_no → {title, date, court, result, summary, reasoning_excerpt}
                              (LLM RAG용 짧은 발췌, 원본 cases.json은 git에 안 들어감)

실행 시점:
  - 원본 자료가 갱신될 때만 (수동)
  - GitHub Actions 자동 빌드에서는 실행 안 함 (원본 자료가 깃에 없으므로)

격리 원칙:
  - 입력: 외부 폴더(판례조회-AI도구) 읽기만
  - 출력: tutor/data/ 안에만
  - 기존 도로교통법-한눈에 파일 미영향

사용법:
  py tutor/build_indexes.py
  py tutor/build_indexes.py --source "C:/Users/user/projects/판례조회-AI도구"
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / 'data'

DEFAULT_SOURCE_DIR = Path(r"C:\Users\user\projects\판례조회-AI도구")

# 조문 헤더 패턴 (해설집): "제N조(제목)" 또는 "제N조의M(제목)" 줄 시작
ARTICLE_HEADER = re.compile(r'^제\s*(\d+)\s*조(?:의\s*(\d+))?\s*(?:\(([^)]*)\))?')

# 조문 인용 패턴 (판례 reasoning 텍스트 안): "도로교통법 제N조" 또는 "제N조" 등
ARTICLE_CITATION = re.compile(r'(?:도로교통법(?:\s*시행(?:령|규칙))?\s*)?제\s*(\d+)\s*조(?:의\s*(\d+))?')

# 본문에서 발췌할 최대 길이 (글자 단위) — LLM RAG용
EXCERPT_MAX_CHARS = 800
# 해설 본문 청크 최대 (너무 길면 LLM 컨텍스트 부담)
COMMENT_CONTENT_MAX_CHARS = 3000


def jo_key(main: str, sub: str | None) -> str:
    """조문번호 키 정규화: '45' 또는 '28의2'."""
    return f"{main}의{sub}" if sub else main


def build_law_comment_index(md_path: Path) -> dict:
    """해설집을 조문번호별 청크로 분할.

    한 조문이 여러 번 등장하는 경우(목차·본문) 가장 긴 청크를 채택.
    """
    if not md_path.exists():
        print(f"❌ {md_path} 없음")
        return {}

    text = md_path.read_text(encoding='utf-8')
    lines = text.split('\n')

    # 조문 헤더 위치 수집
    headers = []  # [(line_idx, jo_key, title)]
    for i, line in enumerate(lines):
        m = ARTICLE_HEADER.match(line.strip())
        if m:
            headers.append((i, jo_key(m.group(1), m.group(2)), m.group(3) or ''))

    # 헤더~다음 헤더 사이를 청크로
    candidates = defaultdict(list)  # jo → [chunk_text, ...]
    for idx, (line_idx, jo, title) in enumerate(headers):
        end_idx = headers[idx + 1][0] if idx + 1 < len(headers) else len(lines)
        chunk = '\n'.join(lines[line_idx:end_idx]).strip()
        if not chunk:
            continue
        candidates[jo].append((title, chunk))

    # 같은 조문 여러 번 등장 시 가장 긴 청크 채택 (목차 vs 본문 — 본문이 더 길다)
    index = {}
    for jo, chunks in candidates.items():
        title, content = max(chunks, key=lambda c: len(c[1]))
        content = content[:COMMENT_CONTENT_MAX_CHARS]
        index[jo] = {
            'title': title.strip(),
            'content': content,
            'occurrences': len(chunks),
        }

    return index


def build_cases_index(cases_path: Path) -> tuple[dict, dict]:
    """cases.json에서 조문번호 → case_no 매핑 + 발췌 메타 구축.

    Returns:
        (index, excerpts)
        - index: {jo_key: [case_no, ...]}
        - excerpts: {case_no: {title, date, court, result, summary, reasoning_excerpt}}
    """
    if not cases_path.exists():
        print(f"❌ {cases_path} 없음")
        return {}, {}

    cases = json.loads(cases_path.read_text(encoding='utf-8'))
    print(f"  📖 cases.json 로드: {len(cases)}건")

    index = defaultdict(list)
    excerpts = {}

    for case in cases:
        case_no = case.get('case_no')
        if not case_no:
            continue

        reasoning = case.get('reasoning', '')

        # 인용된 조문 추출 (중복 제거)
        article_set = set()
        for main, sub in ARTICLE_CITATION.findall(reasoning):
            article_set.add(jo_key(main, sub))

        # 인용 조문이 하나도 없으면 인덱스에 안 넣음 (조문 매칭 불가)
        if not article_set:
            continue

        for jo in article_set:
            index[jo].append(case_no)

        # RAG용 발췌
        reasoning_excerpt = reasoning[:EXCERPT_MAX_CHARS]
        if len(reasoning) > EXCERPT_MAX_CHARS:
            reasoning_excerpt += '... (이하 생략)'

        excerpts[case_no] = {
            'title': case.get('title', ''),
            'date': case.get('date', ''),
            'court': case.get('court', ''),
            'result': case.get('result', ''),
            'year': case.get('year', ''),
            'summary': case.get('summary', '')[:300],
            'reasoning_excerpt': reasoning_excerpt,
        }

    # 같은 조문 내에서 case_no 중복 제거 + 정렬
    index_dedup = {}
    for jo, case_list in index.items():
        unique = sorted(set(case_list))
        index_dedup[jo] = unique

    return index_dedup, excerpts


def main():
    sys.stdout.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(description='해설·판례 인덱스 빌더 (M2.5 Step B)')
    parser.add_argument('--source', type=str, default=str(DEFAULT_SOURCE_DIR),
                        help=f'원본 자료 폴더 (기본: {DEFAULT_SOURCE_DIR})')
    args = parser.parse_args()

    source_dir = Path(args.source)
    if not source_dir.exists():
        print(f"❌ 원본 자료 폴더 없음: {source_dir}")
        sys.exit(1)

    md_path = source_dir / '2024년 도로교통법해설.md'
    cases_path = source_dir / 'cases.json'

    print("=" * 60)
    print("  📚 출근길 법령 튜터 — 인덱스 빌더")
    print("=" * 60)
    print(f"📁 원본 자료: {source_dir}")
    print()

    # 1. 해설집 인덱스
    print("🔍 해설집 파싱 (2024년 도로교통법해설.md)")
    law_index = build_law_comment_index(md_path)
    print(f"  ✅ 조문 청크 {len(law_index)}개 추출")
    sample = list(law_index.items())[:5]
    for jo, info in sample:
        title_preview = info['title'][:30] if info['title'] else '(제목 없음)'
        print(f"    · 제{jo}조 — {title_preview} ({len(info['content'])}자)")
    if len(law_index) > 5:
        print(f"    · ... 외 {len(law_index) - 5}개")
    print()

    # 2. 판례 인덱스 + 발췌
    print("🔍 판례 매핑 (cases.json)")
    case_index, case_excerpts = build_cases_index(cases_path)
    print(f"  ✅ 조문 매핑 {len(case_index)}개 조문")
    print(f"  ✅ 발췌 {len(case_excerpts)}건")
    # 가장 많이 등장하는 조문 5개
    top5 = sorted(case_index.items(), key=lambda kv: -len(kv[1]))[:5]
    print(f"  📊 판례 많은 조문 Top 5:")
    for jo, case_list in top5:
        print(f"    · 제{jo}조 — {len(case_list)}건")
    print()

    # 3. 출력
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_law = OUTPUT_DIR / 'index_law_comment.json'
    out_cases = OUTPUT_DIR / 'index_cases.json'
    out_excerpts = OUTPUT_DIR / 'cases_excerpts.json'

    with open(out_law, 'w', encoding='utf-8') as f:
        json.dump({
            '생성일시': __import__('datetime').datetime.now().isoformat(),
            '설명': '조문번호 → 해설집 본문 청크 (2024년 도로교통법해설.md)',
            '조문수': len(law_index),
            '조문별': law_index,
        }, f, ensure_ascii=False, indent=2)

    with open(out_cases, 'w', encoding='utf-8') as f:
        json.dump({
            '생성일시': __import__('datetime').datetime.now().isoformat(),
            '설명': '조문번호 → 관련 행정심판례 case_no 리스트',
            '조문수': len(case_index),
            '조문별': case_index,
        }, f, ensure_ascii=False, indent=2)

    with open(out_excerpts, 'w', encoding='utf-8') as f:
        json.dump({
            '생성일시': __import__('datetime').datetime.now().isoformat(),
            '설명': 'case_no → RAG용 발췌 메타 (제목·일자·법원·결과·발췌)',
            '발췌수': len(case_excerpts),
            '데이터': case_excerpts,
        }, f, ensure_ascii=False, indent=2)

    print("💾 저장 완료:")
    print(f"  {out_law}  ({out_law.stat().st_size / 1024:.1f} KB)")
    print(f"  {out_cases}  ({out_cases.stat().st_size / 1024:.1f} KB)")
    print(f"  {out_excerpts}  ({out_excerpts.stat().st_size / 1024:.1f} KB)")


if __name__ == '__main__':
    main()
