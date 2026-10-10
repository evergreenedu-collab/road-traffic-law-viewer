# -*- coding: utf-8 -*-
"""보조법령 참고자료 데이터 생성기 (2026-10-10 편성 v2 — Codex 설계 논의+코드리뷰 반영).

편성 v2에서 매일 카드 슬롯이 빠진 보조법령 4그룹(자관법·여객·화물·형소법)을
튜터의 '참고자료' 페이지(tutor/reference.html)로 분리 — 그 데이터 파일을 만든다.

- 소스: study_whitelist.json(교수 관련 조문 + situation 태그)
         + data/three_tier_articles_{group}.json(현행 제목·존재 검증)
         + tutor/data/daily_*.json(과거 ok 학습 카드 재심사·매핑)
- 검증 실패(그룹/목록 누락·조문 없음·제목 불일치·중복·뷰어 파일 없음) 시 exit 1
  — 기존 ref_laws.json 유지.
- 과거 카드 재심사: 제목뿐 아니라 **조문 전문(article_text)이 현행과 일치**할 때만
  'current_match'로 노출 (제목 유지한 채 본문만 개정되는 흔한 케이스 차단 —
  Codex 코드리뷰 치명 지적: 자관법 §34가 페달오조작방지 신설 후에도 노출될 뻔).
- 실행: update_all.py 전역 후처리(실패 없을 때만 1회) + 수동 py tutor/build_ref_laws.py
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ROOT = SCRIPT_DIR.parent
WHITELIST = SCRIPT_DIR / 'data' / 'study_whitelist.json'
OUTPUT = SCRIPT_DIR / 'data' / 'ref_laws.json'

REF_GROUPS = ('car_mgmt', 'passenger_transport', 'cargo_transport', 'crim_proc')

SITUATIONS = {
    'license':   {'label': '면허·자격',      'icon': '🪪'},
    'duty':      {'label': '운전자 의무',    'icon': '📋'},
    'vehicle':   {'label': '차량 안전·관리', 'icon': '🚗'},
    'procedure': {'label': '사고 후 절차',   'icon': '⚖️'},
}

PUBLISH_OK = ('ok', 'ok_re_paired', 'ok_partial')
_DAILY_PAT = re.compile(r'^daily_\d{4}-\d{2}-\d{2}\.json$')


def _load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _article_body_text(art):
    """조문 entry → 항·호·목 포함 전문 (카드 빌더와 동일 조립 규칙)."""
    if not art:
        return ''
    parts = [art.get('조문내용', '')]
    for h in (art.get('항') or []):
        if h.get('항내용'):
            parts.append(h['항내용'])
        for ho in (h.get('호') or []):
            if ho.get('호내용'):
                parts.append('  ' + ho['호내용'])
            for mo in (ho.get('목') or []):
                if mo.get('목내용'):
                    parts.append('    ' + mo['목내용'])
    return '\n'.join(p for p in parts if p.strip())


def _norm_text(s):
    """전문 비교용 정규화 — 줄 단위 strip + 빈 줄 제거 (들여쓰기·후행공백 차이 무시)."""
    return '\n'.join(line.strip() for line in str(s or '').splitlines() if line.strip())


def _scan_past_cards(data_dir):
    """(group, jo) → [{date, title, text}] — ok 상태 보조법령 카드만 (연도 무관)."""
    found = {}
    for f in sorted(Path(data_dir).glob('daily_*.json')):
        if not _DAILY_PAT.match(f.name):
            continue
        try:
            d = _load_json(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f'  ⚠️ 과거 카드 스캔 — {f.name} 손상, 건너뜀 ({e})')
            continue
        for c in d.get('cards', []):
            g = c.get('group')
            if g not in REF_GROUPS or c.get('llm_status') not in PUBLISH_OK:
                continue
            li = c.get('law_info') or {}
            jo = str(li.get('매핑법률조문') or '')
            if not jo:
                continue
            found.setdefault((g, jo), []).append({
                'date': f.name[6:16],
                'title': (li.get('매핑법률조문제목') or '').strip(),
                'text': li.get('article_text') or '',
            })
    return found


def build(root=ROOT, whitelist_path=WHITELIST, output_path=OUTPUT, data_dir=None):
    """ref_laws.json 생성. 검증 오류 리스트 반환 (빈 리스트 = 성공·저장됨)."""
    root = Path(root)
    output_path = Path(output_path)
    data_dir = Path(data_dir) if data_dir else output_path.parent
    wl = _load_json(whitelist_path)
    past = _scan_past_cards(data_dir)
    errors = []
    groups_out = []

    for g in REF_GROUPS:
        info = wl.get(g)
        if not isinstance(info, dict):
            errors.append(f'{g}: 화이트리스트에 그룹 자체가 없음')
            continue
        items = info.get('articles')
        if not isinstance(items, list) or not items:
            errors.append(f'{g}: 화이트리스트 articles 목록이 비어 있음/누락')
            continue
        label = info.get('name', g)
        viewer = f'viewer_{g}.html'
        if not (root / viewer).exists():
            errors.append(f'{g}: 뷰어 파일 없음 ({viewer})')
        try:
            current = (_load_json(root / 'data' / f'three_tier_articles_{g}.json')
                       .get('법률') or {}).get('조문') or {}
        except (json.JSONDecodeError, OSError) as e:
            errors.append(f'{g}: 현행 조문 데이터 로드 실패 ({e})')
            continue
        arts_out = []
        seen = set()
        for item in items:
            jo = str(item.get('article') or '')
            title = (item.get('title') or '').strip()
            cur_entry = current.get(jo) or {}
            cur_title = (cur_entry.get('조문제목') or '').strip()
            if jo in seen:
                errors.append(f'{g} 제{jo}조: 화이트리스트 중복')
                continue
            seen.add(jo)
            if not cur_title:
                errors.append(f'{g} 제{jo}조: 현행 조문에 없음 (조문 이동·삭제 의심)')
                continue
            if title != cur_title:
                errors.append(f"{g} 제{jo}조: whitelist '{title}' ≠ 현행 '{cur_title}'")
                continue
            situation = item.get('situation') or ''
            if situation not in SITUATIONS:
                errors.append(f'{g} 제{jo}조: situation 태그 없음/오타 ({situation!r})')
                continue
            # 재심사 — 제목 + 조문 '전문'이 현행과 일치하는 카드만 노출
            # (본문만 개정된 카드의 옛 AI 해설 노출 차단. 버튼 하나 숨기는 오탐이
            #  개정 전 해설 노출보다 안전 — Codex 코드리뷰)
            cur_norm = _norm_text(_article_body_text(cur_entry))
            cards = sorted(past.get((g, jo), []), key=lambda c: c['date'], reverse=True)
            card_dates = [c['date'] for c in cards
                          if c['title'] == cur_title and _norm_text(c['text']) == cur_norm]
            arts_out.append({
                'article': jo,
                'title': cur_title,
                'topic': item.get('topic', ''),
                'situation': situation,
                'viewer_link': f'../{viewer}?jo={jo}',
                'card_dates': card_dates,
                'card_status': 'current_match' if card_dates else ('stale' if cards else 'none'),
            })
        groups_out.append({'group': g, 'label': label, 'viewer': viewer, 'articles': arts_out})

    if errors:
        return errors

    out = {
        '생성일시': datetime.now().isoformat(),
        '설명': '보조법령 참고자료 — tutor/reference.html 데이터 (build_ref_laws.py 생성)',
        'situations': {k: v['label'] for k, v in SITUATIONS.items()},
        'groups': groups_out,
    }
    tmp = output_path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(output_path)
    n_art = sum(len(g['articles']) for g in groups_out)
    n_card = sum(len(a['card_dates']) for g in groups_out for a in g['articles'])
    n_stale = sum(1 for g in groups_out for a in g['articles'] if a['card_status'] == 'stale')
    print(f'✅ ref_laws.json 생성 — 4그룹 {n_art}개 조문, 재심사 통과 과거 카드 {n_card}장'
          + (f' (본문 개정으로 숨김 {n_stale}건)' if n_stale else ''))
    return []


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    errors = build()
    if errors:
        print('❌ 참고자료 생성 실패 — 검증 불일치 (기존 ref_laws.json 유지):')
        for e in errors:
            print('   ' + e)
        sys.exit(1)


if __name__ == '__main__':
    main()
