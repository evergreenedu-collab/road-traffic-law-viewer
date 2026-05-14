"""
출근길 법령 튜터 — 일일 학습 콘텐츠 생성 (M1: 결정론적 데이터 추출)
=====================================================
입력: ../alarm/data/recent_revisions.json (alarm 워크플로 산출물 — 480 버전 슬림판)
출력: ./data/daily_YYYY-MM-DD.json

알고리즘:
  1. recent_revisions.json 로드
  2. 최근 N일 이내 공포된 버전 + 매핑법률조문 있는 변경조문만 후보 추출
  3. 대상 날짜 기반 결정론적 인덱싱으로 오늘의 후보 1건 선택
     (같은 날짜 = 같은 후보 → 재실행 일관성 보장)
  4. JSON 출력 (M2에서 Gemini가 oneliner·explanation 필드 추가 예정)

격리 원칙:
  - 입력: alarm/data/recent_revisions.json (읽기만)
  - 출력: tutor/data/daily_*.json (튜터 폴더 자체)
  - 기존 워크플로·viewer.html 미영향

사용법:
  python tutor/build_tutor_content.py             # 오늘 날짜로 생성, 파일 저장
  python tutor/build_tutor_content.py --dry-run   # stdout 출력만 (파일 미저장)
  python tutor/build_tutor_content.py --date 2026-05-14
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
INPUT_PATH = SCRIPT_DIR.parent / 'alarm' / 'data' / 'recent_revisions.json'
OUTPUT_DIR = SCRIPT_DIR / 'data'

# 후보 선택 윈도우 (일) — 최근 N일 이내 공포된 자료만 학습 후보로
WINDOW_DAYS = 90

# 결정론적 인덱싱 기준일 (이 날부터 며칠 지났는지로 후보 회전)
EPOCH = datetime(2026, 1, 1)


def load_recent_revisions():
    """alarm 빌드 산출물 로드. 없으면 명확한 에러 메시지 출력 후 종료."""
    if not INPUT_PATH.exists():
        print(f"❌ {INPUT_PATH} 없음 — alarm/build_alarm_data.py가 먼저 실행되어야 합니다")
        sys.exit(1)
    with open(INPUT_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def collect_candidates(revisions_data, today, window_days=WINDOW_DAYS):
    """최근 window_days 이내 공포된 버전 중 매핑법률조문 있는 변경조문 후보 리스트 추출.

    각 후보는 (version, article) 쌍의 정보를 담는다. viewer 딥링크 불가능한 조문
    (시행규칙 일부 — 매핑법률조문이 null인 경우)은 제외.
    """
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
                continue  # viewer 딥링크 불가 — skip
            candidates.append({
                'version': version,
                'article': article,
                'gp_date': gp_date,
            })

    # 공포일자 내림차순 정렬 (최신 우선) — 인덱싱과 결합해 신선도 + 다양성
    candidates.sort(key=lambda c: c['gp_date'], reverse=True)
    return candidates


def select_today_candidate(candidates, target_date):
    """대상 날짜 기반 결정론적 후보 선택.

    같은 날짜 입력은 같은 후보 반환 — 재실행 시 일관성 보장.
    EPOCH로부터의 일수를 후보 개수로 나눈 나머지를 인덱스로 사용.
    """
    if not candidates:
        return None
    days_since = (target_date - EPOCH).days
    idx = days_since % len(candidates)
    return candidates[idx]


def build_daily_content(target_date, candidate):
    """선택된 후보로부터 일일 학습 콘텐츠 JSON 구조 생성.

    candidate가 None이면 SKIP 상태 JSON 반환 (빈 날 허용 정책).
    """
    base = {
        'date': target_date.strftime('%Y-%m-%d'),
        'generated_at': datetime.now().isoformat(),
        'milestone': 'M1',
        'version': 1,
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
        'note': 'M1 출력 — LLM 미생성. M2에서 oneliner·explanation·source_article 필드 추가 예정.',
    })
    return base


def main():
    sys.stdout.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(description='일일 법령 학습 콘텐츠 생성 (M1)')
    parser.add_argument('--dry-run', action='store_true',
                        help='파일 저장 없이 stdout 출력만')
    parser.add_argument('--date', type=str, default=None,
                        help='대상 날짜 (YYYY-MM-DD), 기본=오늘')
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

    revisions = load_recent_revisions()
    print(f"📖 입력: {INPUT_PATH}")
    print(f"  버전수: {revisions.get('버전수', 0)}")
    print(f"  alarm 생성일시: {revisions.get('생성일시', '?')}")

    candidates = collect_candidates(revisions, target_date)
    print(f"\n🔍 후보 추출: 최근 {WINDOW_DAYS}일 이내 공포 + 매핑법률조문 있는 변경조문")
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

    content = build_daily_content(target_date, selected)

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
