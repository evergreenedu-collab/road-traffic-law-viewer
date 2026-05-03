"""
법령 개정 알리미 — 알림 데이터 추출
=====================================
원본 article_history.json에서 알림 카드용 정보만 추출하여 슬림 JSON 생성.

추출 항목 (각 버전당):
  - 법령유형 (법률/시행령/시행규칙)
  - 법령명
  - 공포일자, 시행일자, 공포번호
  - 제개정구분 (일부개정/전부개정/제정 등)
  - 제개정이유 (전체 텍스트)
  - 변경조문: [{조문번호, 조문제목, 변경유형}, ...]  ← "Y" 표시된 조문만

격리 원칙:
  - 입력: ../data/article_history.json (워크플로 빌드 결과 — 우리는 읽기만)
  - 출력: ./data/recent_revisions.json (알림 폴더 자체 — 워크플로 무관)
  - generate_viewer.py와 무관 — 워크플로 회귀 시 영향 없음

사용법:
  python build_alarm_data.py  (alarm 폴더 안에서 실행)
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
INPUT_PATH = SCRIPT_DIR.parent / 'data' / 'article_history.json'
MAP_PATH = SCRIPT_DIR.parent / 'data' / 'three_tier_map.json'
OUTPUT_DIR = SCRIPT_DIR / 'data'
OUTPUT_PATH = OUTPUT_DIR / 'recent_revisions.json'


def build_jo_to_law_jo_map(three_tier_map):
    """3단 매핑에서 (법령유형, 조문키) → {조문키, 조문제목} 사전 생성.

    viewer.html은 법률 조문 기준으로 jo 파라미터를 처리하므로,
    시행령·시행규칙 조문을 직접 점프하려면 그 조문이 매핑된 법률 조문 키가 필요하다.
    제목도 함께 — 알림 UI에서 "법률 제44조 (술에 취한 상태...)" 형태로 표시.
    """
    result = {}
    for entry in three_tier_map.get('매핑', []):
        law_jo = entry.get('법률_조키')
        law_title = entry.get('법률_조문제목', '')
        if not law_jo:
            continue
        info = {'jo': law_jo, 'title': law_title}
        # 항별 매핑
        for hh in entry.get('항별_매핑', []):
            for r in hh.get('시행령', []):
                key = ('시행령', r.get('조키'))
                if key not in result:
                    result[key] = info
            for r in hh.get('시행규칙_직접', []):
                key = ('시행규칙', r.get('조키'))
                if key not in result:
                    result[key] = info
        # 조문전체 매핑
        for c in entry.get('조문전체_매핑', []):
            sub_type = c.get('법령유형')
            sub_jo = c.get('조키')
            if sub_type and sub_jo:
                key = (sub_type, sub_jo)
                if key not in result:
                    result[key] = info
    return result


def extract_changed_articles(version_data, law_type, jo_to_law_map):
    """버전 내 조문 중 조문변경여부=Y인 것만 추출.
    시행령·시행규칙은 매핑된 법률 조문 키와 제목도 함께 추출."""
    changed = []
    for jo_key, jo_info in version_data.get('조문', {}).items():
        if jo_info.get('조문변경여부') != 'Y':
            continue
        # 매핑된 법률 조문 (법률은 자기 자신, 시행령·시행규칙은 매핑 조회)
        if law_type == '법률':
            mapped_law_jo = jo_key
            mapped_law_title = jo_info.get('조문제목', '')
        else:
            mapping_info = jo_to_law_map.get((law_type, jo_key))
            mapped_law_jo = mapping_info['jo'] if mapping_info else None
            mapped_law_title = mapping_info['title'] if mapping_info else ''
        changed.append({
            '조문번호': jo_key,
            '조문제목': jo_info.get('조문제목', ''),
            '조문제개정유형': jo_info.get('조문제개정유형', ''),
            '조문시행일자': jo_info.get('조문시행일자', ''),
            '매핑법률조문': mapped_law_jo,
            '매핑법률조문제목': mapped_law_title,
        })
    return changed


def main():
    sys.stdout.reconfigure(encoding='utf-8')

    if not INPUT_PATH.exists():
        print(f"❌ {INPUT_PATH} 없음 — 워크플로가 먼저 실행되어야 합니다")
        sys.exit(1)

    print("=" * 60)
    print("  법령 개정 알리미 — 알림 데이터 추출")
    print("=" * 60)
    print(f"📖 입력: {INPUT_PATH}")
    print(f"📖 매핑: {MAP_PATH}")

    with open(INPUT_PATH, 'r', encoding='utf-8') as f:
        history = json.load(f)

    # 3단 매핑 로드 — 시행령·시행규칙 조문 → 법률 조문 점프용
    if MAP_PATH.exists():
        with open(MAP_PATH, 'r', encoding='utf-8') as f:
            three_tier_map = json.load(f)
        jo_to_law_map = build_jo_to_law_jo_map(three_tier_map)
        print(f"  매핑 사전 생성: {len(jo_to_law_map)}개 (시행령·시행규칙 → 법률)")
    else:
        jo_to_law_map = {}
        print(f"  ⚠️ 매핑 파일 없음 — 시행령·시행규칙 조문 점프 비활성")

    versions = []
    for law_type, law_info in history.get('법령', {}).items():
        for v in law_info.get('버전', []):
            changed = extract_changed_articles(v, law_type, jo_to_law_map)
            versions.append({
                '법령유형': law_type,
                '법령명': v.get('법령명', law_info.get('법령명', '')),
                '공포일자': v.get('공포일자', ''),
                '시행일자': v.get('시행일자', ''),
                '공포번호': v.get('공포번호', ''),
                '제개정구분': v.get('제개정구분', ''),
                '제개정이유': v.get('제개정이유', '').strip(),
                '변경조문수': len(changed),
                '변경조문': changed,
            })

    # 공포일자 내림차순 정렬 (최신이 먼저)
    versions.sort(key=lambda v: v['공포일자'], reverse=True)

    # 출력
    OUTPUT_DIR.mkdir(exist_ok=True)
    output = {
        '생성일시': datetime.now().isoformat(),
        '설명': '도로교통법 3개 법령의 개정 이력 (알림용 슬림판)',
        '버전수': len(versions),
        '버전들': versions,
    }
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(OUTPUT_PATH) / 1024

    print(f"\n📊 추출 결과:")
    print(f"  전체 버전: {len(versions)}개")
    # 법령별 통계
    from collections import Counter
    law_count = Counter(v['법령유형'] for v in versions)
    for lt, cnt in law_count.most_common():
        print(f"  {lt}: {cnt}개 버전")

    # 변경조문 통계
    total_changed = sum(v['변경조문수'] for v in versions)
    print(f"  총 변경 조문: {total_changed}건")

    # 최근 90일 (오늘 기준 — 발행 시점)
    today = datetime.now()
    recent_90 = [v for v in versions
                 if v['공포일자']
                 and (today - datetime.strptime(v['공포일자'], '%Y%m%d')).days <= 90]
    recent_30 = [v for v in versions
                 if v['공포일자']
                 and (today - datetime.strptime(v['공포일자'], '%Y%m%d')).days <= 30]
    print(f"  최근 90일 이내: {len(recent_90)}개")
    print(f"  최근 30일 이내 (NEW 뱃지 대상): {len(recent_30)}개")

    print(f"\n💾 저장: {OUTPUT_PATH} ({size_kb:.1f}KB)")


if __name__ == '__main__':
    main()
