# -*- coding: utf-8 -*-
"""2026-10-10 운영 개선(교차검증 합의) 회귀 테스트.

실행: py -X utf8 tutor/test_tutor_fixes.py
대상: 멱등화 판정(_is_final_daily), 키워드 누출 출처기반 판정(detect_external_keywords),
     최근개정 기간 판정(_is_recent_revision), 목요일 격주 슬롯(_resolve_thursday_slot),
     교특법 격주 조문 순환(_group_occurrence_index).
"""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
import build_tutor_content as btc


def test_is_final_daily():
    ok_doc = {'status': 'ok', 'cards': [{'llm_status': 'ok', 'content_tier': 'full'}]}
    assert btc._is_final_daily(ok_doc), "정상 카드는 재생성 스킵(final)"

    src_only = {'status': 'ok', 'cards': [{'llm_status': 'skip_call_failed',
                                           'content_tier': 'source_only'}]}
    assert not btc._is_final_daily(src_only), "source_only 폴백은 재시도 대상"

    leaked = {'status': 'ok', 'cards': [{'llm_status': 'skip_external_keywords_leaked',
                                         'content_tier': 'full'}]}
    assert not btc._is_final_daily(leaked), "실패 카드는 재시도 대상"

    assert btc._is_final_daily({'status': 'weekend'}), "주말 문서는 final"
    assert not btc._is_final_daily(None), "손상 문서는 재생성"
    assert not btc._is_final_daily({'status': 'ok', 'cards': []}), "카드 없으면 재생성"


def test_detect_external_keywords():
    out = {'explanation': '이 판례는 음주운전 중 사고를 다룬다'}
    jo_text = '제148조(벌칙) 교통사고 발생 시의 조치를 하지 아니한 사람'
    case_text = '피고인은 혈중알코올농도 0.1% 상태의 음주운전 중 ...'

    leaked = btc.detect_external_keywords(out, jo_text)
    assert '음주운전' in leaked, "조문에 없는 키워드는 누출"

    leaked2 = btc.detect_external_keywords(out, jo_text, extra_allowed_texts=(case_text,))
    assert leaked2 == [], "제공된 판례 원문에 있는 키워드는 누출 아님"

    leaked3 = btc.detect_external_keywords(out, jo_text, extra_allowed_texts=('무관한 텍스트',))
    assert '음주운전' in leaked3, "허용 근거 어디에도 없으면 여전히 누출"


def test_is_recent_revision():
    v_2011 = {'시행일자': '20111209'}
    assert not btc._is_recent_revision(v_2011, {}, '20261010'), "2011년 개정은 최근 아님"

    v_recent = {'시행일자': '20260901'}
    assert btc._is_recent_revision(v_recent, {}, '20261010'), "39일 전 시행은 최근"

    art_recent = {'조문시행일자': '20260901'}
    assert btc._is_recent_revision({'시행일자': '20110101'}, art_recent, '20261010'), \
        "조문시행일자 우선"

    assert not btc._is_recent_revision(None, None, '20261010'), "개정 없으면 False"
    assert not btc._is_recent_revision({'시행일자': '20270101'}, {}, '20261010'), \
        "미래 시행은 False"


def test_thursday_biweekly():
    thu_tlspc = datetime(2026, 10, 15)   # 주차 41 (홀수) — 교특법 주
    thu_tkga = datetime(2026, 10, 22)    # 주차 42 (짝수) — 특가법 주
    assert thu_tlspc.weekday() == 3 and thu_tkga.weekday() == 3
    assert btc._resolve_thursday_slot(thu_tlspc) == ('article', 'tlspc')
    assert btc._resolve_thursday_slot(thu_tkga) == ('article', 'tkga')
    assert btc._resolve_thursday_slot(datetime(2026, 10, 29)) == ('article', 'tlspc')


def test_weekday_slots_v2():
    # 2026-10-10 사용자 확정 편성: 월·수 법률 / 화 하위법령 / 목 격주 / 금 판례
    assert btc.WEEKDAY_SLOTS[0] == ('article', 'road')
    assert btc.WEEKDAY_SLOTS[1] == ('sub_laws', 'road')
    assert btc.WEEKDAY_SLOTS[2] == ('article', 'road')
    assert btc.WEEKDAY_SLOTS[4] == ('case', 'road')
    assert 'tkga' in btc.ROTATE_CASE_GROUPS, "특가법도 판례 회전"


def test_road_exclusions():
    excl = btc._road_excluded_articles()
    for jo in ('102', '104', '109', '116', '147의3'):
        assert jo in excl, f"제{jo}조(학원·행정)는 제외 목록"
    for jo in ('44', '54', '93', '148'):
        assert jo not in excl, f"제{jo}조(핵심)는 출제 유지"
    arts = {'44': {'weight_score': 1.0}, '104': {'weight_score': 99.0}}
    picked = btc._select_article_stride(arts, datetime(2026, 10, 12), {})
    assert picked == '44', "제외 조문은 가중치가 높아도 선정 금지"


def test_sub_laws_selection():
    # 전날(월) 제44조 → 위임 하위조문 묶음 선정 (실데이터 three_tier_map 사용)
    sch = {'2026-10-12': {'type': 'article', 'group': 'road', 'article': '44'}}
    arts = {'44': {'weight_score': 0.5}}
    sel = btc._make_sub_laws_selection(datetime(2026, 10, 13), arts, sch)
    assert sel and sel['card_type'] == 'sub_laws' and sel['jo'] == '44'
    assert sel['subs'] and all(s['본문'] for s in sel['subs']), "하위조문 본문 로드"
    assert all(s['법령유형'] in ('시행령', '시행규칙') for s in sel['subs'])
    # 전날 조문에 위임이 없으면(제1조 목적) 주제 묶음 폴백
    sch2 = {'2026-10-12': {'type': 'article', 'group': 'road', 'article': '1'}}
    sel2 = btc._make_sub_laws_selection(datetime(2026, 10, 13), {'1': {}}, sch2)
    assert sel2 and sel2.get('topic_id'), "주제 묶음 폴백 작동"


def test_tlspc_occurrence_biweekly():
    # 격주 교특법 목요일(홀수 주차)들의 occurrence가 1씩 증가해야
    # 조문 2개(제3·4조)가 번갈아 나온다 (week_index 그대로면 홀수만 나와 한 조문 고정).
    occ1 = btc._group_occurrence_index('tlspc', datetime(2026, 10, 15))
    occ2 = btc._group_occurrence_index('tlspc', datetime(2026, 10, 29))
    occ3 = btc._group_occurrence_index('tlspc', datetime(2026, 11, 12))
    assert occ2 == occ1 + 1 and occ3 == occ2 + 1, f"교특법 occurrence 연속 증가: {occ1},{occ2},{occ3}"
    assert (occ1 % 2) != (occ2 % 2), "조문 2개가 번갈아 선정되려면 홀짝이 교대해야"


def test_schedule_needs_retry():
    # '원래 슬롯(case/sub_laws) 실패→article 폴백' 날은 성공 카드여도 재생성해 재시도
    sch = {'2026-10-13': {'type': 'article', 'group': 'road', 'article': '44',
                          'fallback_from_case': {'reason': 'selection_failed'}},
           '2026-10-14': {'type': 'article', 'group': 'road', 'article': '12'},
           '2026-10-15': {'type': 'case', 'group': 'road', 'article': '54'},
           '2026-10-20': {'type': 'article', 'group': 'road', 'article': '7',
                          'fallback_from_sub_laws': {'reason': 'no_sub_refs'}}}
    assert btc._schedule_needs_retry(sch, datetime(2026, 10, 13)), "case 폴백 표식은 재시도"
    assert btc._schedule_needs_retry(sch, datetime(2026, 10, 20)), "sub_laws 폴백 표식은 재시도"
    assert not btc._schedule_needs_retry(sch, datetime(2026, 10, 14)), "정상 article은 스킵"
    assert not btc._schedule_needs_retry(sch, datetime(2026, 10, 15)), "성공 case는 스킵"
    assert not btc._schedule_needs_retry(sch, datetime(2026, 10, 16)), "미배정일은 스킵"


def test_checkpoint_corrupt_quarantine():
    # JSON 문법 깨짐·내부 구조 손상 둘 다 .corrupt.*로 격리 후 재수집 (3개월 장애 재발 방지)
    import importlib, tempfile, os, json as _json
    sys.path.insert(0, str(Path(__file__).parent.parent))
    cah = importlib.import_module('collect_article_history')
    with tempfile.TemporaryDirectory() as td:
        old_dd = cah.DATA_DIR
        cah.DATA_DIR = td
        try:
            for payload in ('{"깨진 json', '{"법령": {"법률": null}}'):
                chk = os.path.join(td, 'article_history_checkpoint.json')
                with open(chk, 'w', encoding='utf-8') as f:
                    f.write(payload)
                old_group = cah.LAW_GROUP
                cah.LAW_GROUP = []   # API 호출 없이 로드·격리 경로만 실행
                try:
                    cah.collect_all()
                finally:
                    cah.LAW_GROUP = old_group
                assert not os.path.exists(chk) or _json.load(open(chk, encoding='utf-8')), \
                    "손상 체크포인트가 그대로 남아 있음"
                corrupts = [n for n in os.listdir(td) if '.corrupt.' in n]
                assert corrupts, f"격리 파일 없음 (payload={payload[:20]})"
                for n in os.listdir(td):
                    os.remove(os.path.join(td, n))
        finally:
            cah.DATA_DIR = old_dd


def test_publish_gate_statuses():
    # 2026-10-10 사용자 결정: AI 해설 없으면 발행 금지 — 허용 상태는 LLM 성공군만
    for s in ('ok', 'ok_re_paired', 'ok_partial'):
        assert s in btc.PUBLISH_OK_STATUSES, f"{s}는 발행 허용"
    for s in ('skip_call_failed', 'skip_external_keywords_leaked', 'skip_llm_returned_skip',
              'skip_verification_failed', 'simple_other_group', 'skipped_by_flag'):
        assert s not in btc.PUBLISH_OK_STATUSES, f"{s}는 발행 금지(재시도 대상)"
    assert 'simple_other_group' not in btc.FINAL_CARD_STATUSES, "LLM 없는 카드는 확정 아님"


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"✅ {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"❌ {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} 통과")
    sys.exit(1 if failed else 0)
