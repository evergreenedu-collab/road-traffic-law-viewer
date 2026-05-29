"""
도로교통법 한눈에 — 전체 빌드 자동화
======================================
법령이 새로 개정됐을 때 또는 처음 설치 시 한 줄로 모든 데이터를 수집·빌드한다.

사용법:
    python update_all.py              # 기본 (증분 — 신규만 수집·다운로드)
    python update_all.py --rebuild    # 모든 단계 강제 재실행 (수집 데이터 재활용)
    python update_all.py --skip-collect  # 수집 건너뛰고 빌드만 (data/ 이미 있을 때)
    python update_all.py --no-pdfs    # 별표 PDF 다운로드 건너뛰기 (가벼운 테스트)

11단계 (소요시간 처음 시 ~35분, 증분 갱신 시 ~수 분):
    1. build_3tier_map.py                    [~10초]
    2. collect_full_history.py               [~30초, API]
    3. collect_article_history.py            [~6분, API, 증분]
    4. build_article_timeline.py             [~5초]
    5. build_text_diff.py                    [~10초]
    6. collect_attached_tables_history.py    [~3분, API]
    7. build_attached_tables_diff.py         [~5초]
    8. build_attached_tables.py              [~5분 첫 회 / 수초 증분, 별지 PDF base64]
    9. build_cascade_events.py               [~5초]
    10. download_table_pdfs.py               [~25분 첫 회 / 수초 증분]
    11. generate_viewer.py                   [~5초]
"""

import argparse
import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Phase 3 (2026-05-25): multi-group 자동 갱신 — build_3tier_map에서 LAW_GROUPS 공유
sys.path.insert(0, SCRIPT_DIR)
from build_3tier_map import LAW_GROUPS as _SHARED_LAW_GROUPS
# generate_viewer의 GROUP_ENABLED (활성화된 그룹만 갱신 대상)
from generate_viewer import GROUP_ENABLED as _GROUP_ENABLED

# STAGES 분류:
#   - kind: collect / build / pdfs (--skip-collect, --no-pdfs 등 옵션과 연동)
#   - sub_only: 시행령 또는 시행규칙이 있는 그룹에만 의미 있음
#     · 단일법 그룹(tkga·crim_proc)은 자동 스킵 — 시행령/시행규칙 자체 없음
#     · tlspc는 시행령 있으므로 실행됨 (실제로는 별표 0개라 단계는 빠르게 끝남)
#   - road_only: build_article_timeline 등 multi-group 미지원 단계 (road 외 그룹은 스킵)
STAGES = [
    # (스크립트, 표시명, 분류, 예상소요, sub_only, road_only)
    ("build_3tier_map.py",                    "3단 매핑",                   "build",  "10초",   False, False),
    ("collect_full_history.py",               "전체 연혁 수집",              "collect","30초",   False, False),
    ("collect_article_history.py",            "조문별 변경 수집",            "collect","6분",    False, False),
    ("build_article_timeline.py",             "타임라인 빌드",               "build",  "5초",    False, True),
    ("build_text_diff.py",                    "본문 전후비교 빌드",          "build",  "10초",   False, False),
    ("collect_attached_tables_history.py",    "별표 시점별 본문 수집",        "collect","3분",    True,  False),
    ("build_attached_tables_diff.py",         "별표 전후비교 빌드",          "build",  "5초",    True,  False),
    ("build_attached_tables.py",              "별표/별지 최신 스냅샷 빌드",   "build",  "수초~5분", True, False),
    ("build_cascade_events.py",               "캐스케이드 이벤트 빌드",       "build",  "5초",    False, False),
    # 2026-05-29: 알람 데이터 갱신 — viewer의 📢 최근 개정 알림 모달용. road 전용 (alarm.html은 road에만 표시).
    ("alarm/build_alarm_data.py",             "최근 개정 알림 데이터 빌드",   "build",  "5초",    False, True),
    ("download_table_pdfs.py",                "별표 PDF 다운로드 (증분)",     "pdfs",   "수초~25분", True, False),
    ("generate_viewer.py",                    "최종 뷰어 생성",              "build",  "5초",    False, False),
]


def _group_has_subordinate(group_key):
    """그룹에 시행령 또는 시행규칙이 있는지 (별표 단계 의미 여부 판정)"""
    g = _SHARED_LAW_GROUPS.get(group_key, {})
    return ("시행령" in g) or ("시행규칙" in g)


def run_step(idx, total, script, label, est, group="road"):
    print()
    print("━" * 60)
    print(f"[{idx}/{total}] {label}  ({script}, 예상 {est}) — 그룹: {group}")
    print("━" * 60)
    start = time.time()
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    # road는 기본값(인자 없음)으로 호출해 기존 단일 그룹 흐름과 동일 동작 — 회귀 0
    cmd = [sys.executable, os.path.join(SCRIPT_DIR, script)]
    if group != "road":
        cmd += ["--group", group]
    result = subprocess.run(cmd, cwd=SCRIPT_DIR, env=env)
    elapsed = time.time() - start
    if result.returncode != 0:
        print(f"\n❌ 실패: {script} (그룹 {group}, 반환코드 {result.returncode}, {elapsed:.1f}초)")
        return False
    print(f"✓ 완료 ({elapsed:.1f}초)")
    return True


def main():
    p = argparse.ArgumentParser(description="도로교통법 한눈에 — 전체 빌드 자동화 (multi-group)")
    p.add_argument("--rebuild", action="store_true", help="(예약) 모든 단계 강제 재실행")
    p.add_argument("--skip-collect", action="store_true", help="API 수집 건너뛰고 빌드만")
    p.add_argument("--no-pdfs", action="store_true", help="별표 PDF 다운로드 건너뛰기")
    p.add_argument("--group", default=None, choices=list(_SHARED_LAW_GROUPS.keys()),
                   help="특정 법령 그룹만 갱신 (예: --group car_mgmt). 미지정 시 GROUP_ENABLED 전체 순회")
    args = p.parse_args()

    # 갱신 대상 그룹 결정
    if args.group:
        groups_to_run = [args.group]
    else:
        # GROUP_ENABLED 순서를 LAW_GROUPS 정의 순서로 정렬 (road 우선)
        groups_to_run = [g for g in _SHARED_LAW_GROUPS.keys() if g in _GROUP_ENABLED]

    print("=" * 60)
    print("  도로교통법 한눈에 — 전체 빌드 자동화 (multi-group)")
    print("=" * 60)
    print(f"\n갱신 대상 그룹: {', '.join(groups_to_run)} ({len(groups_to_run)}개)")

    overall_start = time.time()
    failed = []

    for gi, group in enumerate(groups_to_run, 1):
        # 그룹별로 STAGES 필터링
        has_sub = _group_has_subordinate(group)
        selected = []
        for s in STAGES:
            script, label, kind, est, sub_only, road_only = s
            if args.skip_collect and kind == "collect":
                continue
            if args.no_pdfs and kind == "pdfs":
                continue
            if sub_only and not has_sub:
                # 단일 법률 그룹(tkga·crim_proc)은 별표 단계 의미 없음 — 자동 스킵
                continue
            if road_only and group != "road":
                # build_article_timeline 등 multi-group 미지원 단계
                continue
            selected.append(s)

        print()
        print("█" * 60)
        print(f"█ 그룹 [{gi}/{len(groups_to_run)}]: {group}  —  {len(selected)}개 단계")
        print("█" * 60)

        for i, (script, label, kind, est, sub_only, road_only) in enumerate(selected, 1):
            ok = run_step(i, len(selected), script, label, est, group=group)
            if not ok:
                failed.append(f"{group}/{script}")
                print(f"\n중단 — {group} 그룹의 {script}에서 실패.")
                print(f"부분 진행 후 재개: python update_all.py --group {group} --skip-collect 등")
                # 한 그룹 실패해도 다음 그룹은 진행 (자동 워크플로 안정성)
                # 단, 다른 그룹은 의존 파일 공유 없으므로 안전
                print(f"⚠️ {group} 그룹은 건너뛰고 다음 그룹 진행")
                break

    total_elapsed = time.time() - overall_start
    print()
    print("=" * 60)
    if failed:
        print(f"⚠️ 일부 실패  총 {total_elapsed/60:.1f}분")
        print(f"실패 단계: {', '.join(failed)}")
    else:
        print(f"🎉 전체 빌드 완료!  총 {total_elapsed/60:.1f}분")
    print("=" * 60)
    print(f"\n결과 확인:")
    print(f"  python serve.py")
    print(f"  → 브라우저 자동 오픈: http://localhost:8000/viewer.html")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
