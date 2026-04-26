"""
도로교통법 한눈에 — 전체 빌드 자동화
======================================
법령이 새로 개정됐을 때 또는 처음 설치 시 한 줄로 모든 데이터를 수집·빌드한다.

사용법:
    python update_all.py              # 기본 (증분 — 신규만 수집·다운로드)
    python update_all.py --rebuild    # 모든 단계 강제 재실행 (수집 데이터 재활용)
    python update_all.py --skip-collect  # 수집 건너뛰고 빌드만 (data/ 이미 있을 때)
    python update_all.py --no-pdfs    # 별표 PDF 다운로드 건너뛰기 (가벼운 테스트)

10단계 (소요시간 처음 시 ~30분, 증분 갱신 시 ~수 분):
    1. build_3tier_map.py                    [~10초]
    2. collect_full_history.py               [~30초, API]
    3. collect_article_history.py            [~6분, API, 증분]
    4. build_article_timeline.py             [~5초]
    5. build_text_diff.py                    [~10초]
    6. collect_attached_tables_history.py    [~3분, API]
    7. build_attached_tables_diff.py         [~5초]
    8. build_cascade_events.py               [~5초]
    9. download_table_pdfs.py                [~25분 첫 회 / 수초 증분]
    10. generate_viewer.py                   [~5초]
"""

import argparse
import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

STAGES = [
    # (스크립트, 표시명, 분류, 예상소요)
    ("build_3tier_map.py",                    "3단 매핑",                   "build",  "10초"),
    ("collect_full_history.py",               "전체 연혁 수집",              "collect","30초"),
    ("collect_article_history.py",            "조문별 변경 수집",            "collect","6분"),
    ("build_article_timeline.py",             "타임라인 빌드",               "build",  "5초"),
    ("build_text_diff.py",                    "본문 전후비교 빌드",          "build",  "10초"),
    ("collect_attached_tables_history.py",    "별표 시점별 본문 수집",        "collect","3분"),
    ("build_attached_tables_diff.py",         "별표 전후비교 빌드",          "build",  "5초"),
    ("build_cascade_events.py",               "캐스케이드 이벤트 빌드",       "build",  "5초"),
    ("download_table_pdfs.py",                "별표 PDF 다운로드 (증분)",     "pdfs",   "수초~25분"),
    ("generate_viewer.py",                    "최종 뷰어 생성",              "build",  "5초"),
]


def run_step(idx, total, script, label, est):
    print()
    print("━" * 60)
    print(f"[{idx}/{total}] {label}  ({script}, 예상 {est})")
    print("━" * 60)
    start = time.time()
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPT_DIR, script)],
        cwd=SCRIPT_DIR,
        env=env,
    )
    elapsed = time.time() - start
    if result.returncode != 0:
        print(f"\n❌ 실패: {script} (반환코드 {result.returncode}, {elapsed:.1f}초)")
        return False
    print(f"✓ 완료 ({elapsed:.1f}초)")
    return True


def main():
    p = argparse.ArgumentParser(description="도로교통법 한눈에 — 전체 빌드 자동화")
    p.add_argument("--rebuild", action="store_true", help="(예약) 모든 단계 강제 재실행")
    p.add_argument("--skip-collect", action="store_true", help="API 수집 건너뛰고 빌드만")
    p.add_argument("--no-pdfs", action="store_true", help="별표 PDF 다운로드 건너뛰기")
    args = p.parse_args()

    print("=" * 60)
    print("  도로교통법 한눈에 — 전체 빌드 자동화")
    print("=" * 60)

    selected = []
    for s in STAGES:
        script, label, kind, est = s
        if args.skip_collect and kind == "collect":
            print(f"⏭  건너뜀: {label} (--skip-collect)")
            continue
        if args.no_pdfs and kind == "pdfs":
            print(f"⏭  건너뜀: {label} (--no-pdfs)")
            continue
        selected.append(s)

    print(f"\n총 {len(selected)}개 단계 실행 예정.")
    overall_start = time.time()
    failed = []
    for i, (script, label, kind, est) in enumerate(selected, 1):
        ok = run_step(i, len(selected), script, label, est)
        if not ok:
            failed.append(script)
            print(f"\n중단 — {script}에서 실패. 위 오류를 확인하고 다시 실행하세요.")
            print(f"부분 진행 후 재개하려면: python update_all.py --skip-collect 등 옵션 활용.")
            sys.exit(1)

    total_elapsed = time.time() - overall_start
    print()
    print("=" * 60)
    print(f"🎉 전체 빌드 완료!  총 {total_elapsed/60:.1f}분")
    print("=" * 60)
    print(f"\n결과 확인:")
    print(f"  python serve.py")
    print(f"  → 브라우저 자동 오픈: http://localhost:8000/viewer.html")


if __name__ == "__main__":
    main()
