"""
별표/별지 최신 스냅샷 빌드 (attached_tables.json)
==================================================
attached_tables_history.json(시점별 본문)에서 각 법령의 최신 공포일자 슬라이스만
추출하여, 별표 모달이 사용하는 attached_tables.json을 자동 생성한다.

자동화 배경:
    매주 자동 갱신 워크플로에서 attached_tables.json이 별도 빌드 단계 없이
    누락되어, generate_viewer.py가 fallback 경로로 진입하면서 HWP·PDF_BASE64를
    빈 값으로 채우는 회귀가 발생했다 (2026-04-30, Run #25165176026).
    이 스크립트가 그 빈자리를 메워 fallback 자체가 작동할 일이 없도록 한다.

사용법:
    python build_attached_tables.py
    python build_attached_tables.py --no-base64   # 서식 PDF base64 다운로드 건너뛰기 (테스트용)

입력:
    data/attached_tables_history.json   ← collect_attached_tables_history.py 산출
    data/article_history.json           ← collect_full_history.py 산출
    data/attached_tables.json (옵션)    ← 직전 빌드 결과 — 변경 없는 별지의 base64 캐시

출력:
    data/attached_tables.json
    {
      "시행령": {
        "별표 1": {
          "구분": "별표", "번호": "1",
          "제목": "...", "내용": "...",
          "PDF": "/LSW/flDownload.do?flSeq=...",
          "HWP": "/LSW/flDownload.do?flSeq=...",
          "PDF_BASE64": ""    # 별표는 PDF가 커서 base64 안 만듦 (로컬 경로 사용)
        }, ...
      },
      "시행규칙": {
        "별표 1": {... PDF_BASE64="" ...},
        "서식 1": {... PDF_BASE64="JVBERi0xLjQK..." ...}    # 별지(서식)는 base64 임베드
      }
    }

처리 로직:
    1. attached_tables_history.json + article_history.json 로드
    2. 직전 attached_tables.json을 캐시로 로드 (있으면)
    3. 시행령/시행규칙 각각:
       - 법령의 최신 공포일자 (versions[0]['공포일자'])
       - history의 각 별표 중 그 공포일자에 데이터가 있는 것만 채택 (= 현재 존재)
    4. PDF_BASE64 처리:
       - 별표 → 빈 값 (generate_viewer.py가 로컬 경로 사용)
       - 서식 → 캐시 일치(PDF_URL 동일)하면 재사용, 다르면 새로 다운로드 + 인코딩
"""

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime

import requests

from api_utils import request_xml_with_retry  # collect 스크립트가 쓰는 헬퍼와 공유

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
HISTORY_PATH = os.path.join(DATA_DIR, "attached_tables_history.json")
ART_HISTORY_PATH = os.path.join(DATA_DIR, "article_history.json")
OUTPUT_PATH = os.path.join(DATA_DIR, "attached_tables.json")

LAW_GO_KR = "https://www.law.go.kr"
DOWNLOAD_DELAY = 0.6  # API 매너 — 호출 간격


def parse_key(tname: str):
    """별표 키에서 구분/번호 분리. 예: '별표 1' → ('별표','1'), '서식 28의2' → ('서식','28의2')."""
    parts = tname.split(" ", 1)
    구분 = parts[0] if parts else "별표"
    번호 = parts[1] if len(parts) > 1 else ""
    return 구분, 번호


def download_pdf_base64(pdf_url: str) -> str:
    """법제처 다운로드 URL에서 PDF 받아 base64로 인코딩.
    실패 시 빈 문자열 반환 (별지 모달은 그래도 PDF_URL로 fallback 가능)."""
    if not pdf_url:
        return ""
    full_url = pdf_url if pdf_url.startswith("http") else LAW_GO_KR + pdf_url
    try:
        r = requests.get(full_url, timeout=30)
        if r.status_code != 200 or not r.content:
            return ""
        return base64.b64encode(r.content).decode("ascii")
    except Exception as e:
        print(f"    ⚠️ PDF 다운로드 실패 ({pdf_url[:60]}): {e}")
        return ""


def main():
    p = argparse.ArgumentParser(description="별표/별지 최신 스냅샷 빌드")
    p.add_argument("--no-base64", action="store_true",
                   help="서식 PDF base64 다운로드 건너뛰기 (테스트용)")
    args = p.parse_args()

    print("=" * 60)
    print("  별표/별지 최신 스냅샷 빌드 (attached_tables.json)")
    print("=" * 60)

    # 입력 로드
    if not os.path.exists(HISTORY_PATH):
        print(f"❌ {HISTORY_PATH} 없음 — collect_attached_tables_history.py 먼저 실행")
        sys.exit(1)
    if not os.path.exists(ART_HISTORY_PATH):
        print(f"❌ {ART_HISTORY_PATH} 없음 — collect_full_history.py 먼저 실행")
        sys.exit(1)

    print("📖 입력 로딩...")
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        tab_hist = json.load(f)
    with open(ART_HISTORY_PATH, "r", encoding="utf-8") as f:
        art_hist = json.load(f)

    # 캐시 로드 (직전 빌드 결과 — 변경 없는 별지의 base64 재사용)
    cache = {}
    if os.path.exists(OUTPUT_PATH):
        try:
            with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
                cache = json.load(f)
            print(f"📦 직전 빌드 캐시 발견 (PDF_BASE64 재사용)")
        except Exception:
            cache = {}

    result = {"시행령": {}, "시행규칙": {}}
    base64_new = 0
    base64_reused = 0
    base64_failed = 0

    for law_type in ["시행령", "시행규칙"]:
        # 법령 최신 공포일자 (versions는 공포일자 내림차순 정렬됨)
        versions = art_hist["법령"].get(law_type, {}).get("버전", [])
        if not versions:
            print(f"⚠️ {law_type}: versions 없음 — 건너뜀")
            continue
        latest_pub = versions[0]["공포일자"]
        print(f"\n📋 {law_type} (최신 공포일자: {latest_pub})")

        snapshots_by_table = tab_hist.get(law_type, {})
        cache_law = cache.get(law_type, {})

        included = 0
        excluded = 0
        for tname, snapshots in snapshots_by_table.items():
            # 최신 공포일자에 데이터가 있는 별표만 = 현재 존재
            if latest_pub not in snapshots:
                excluded += 1
                continue
            snap = snapshots[latest_pub]

            구분, 번호 = parse_key(tname)
            cached_entry = cache.get(law_type, {}).get(tname, {})
            entry = {
                "구분": 구분,
                "번호": 번호,
                "제목": snap.get("제목", ""),
                "내용": snap.get("내용", ""),
                "PDF": snap.get("PDF_URL", ""),
                # HWP: history에 HWP_URL이 있으면 사용, 없으면 캐시 재사용 (collect 스크립트가
                # HWP_URL 추출하기 시작한 시점 이전의 옛 history에 대한 폴백)
                "HWP": snap.get("HWP_URL", "") or cached_entry.get("HWP", ""),
                "PDF_BASE64": "",
            }

            # PDF_BASE64: 서식만 (별표는 generate_viewer.py가 로컬 경로로 처리)
            if 구분 == "서식" and entry["PDF"] and not args.no_base64:
                cached_entry = cache_law.get(tname, {})
                # 캐시 일치 조건: PDF URL 동일 + 캐시에 base64 보유
                if cached_entry.get("PDF") == entry["PDF"] and cached_entry.get("PDF_BASE64"):
                    entry["PDF_BASE64"] = cached_entry["PDF_BASE64"]
                    base64_reused += 1
                else:
                    # 새로 다운로드
                    time.sleep(DOWNLOAD_DELAY)
                    b64 = download_pdf_base64(entry["PDF"])
                    if b64:
                        entry["PDF_BASE64"] = b64
                        base64_new += 1
                    else:
                        base64_failed += 1
                    if (base64_new + base64_failed) % 20 == 0:
                        print(f"    📥 다운로드 진행: 신규 {base64_new}, 실패 {base64_failed}")

            result[law_type][tname] = entry
            included += 1

        print(f"  포함 {included}개 (최신 시점에 존재) / 제외 {excluded}개 (폐지·번호 변경 등)")

    # 저장
    print("\n💾 저장 중...")
    # 임시 파일에 쓴 후 rename — 빌드 도중 실패 시 기존 파일 보존
    tmp_path = OUTPUT_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    os.replace(tmp_path, OUTPUT_PATH)
    size_mb = os.path.getsize(OUTPUT_PATH) / (1024 * 1024)

    print()
    print("=" * 60)
    print(f"✅ 완료: {OUTPUT_PATH} ({size_mb:.1f}MB)")
    print(f"  시행령: {len(result['시행령'])}개")
    print(f"  시행규칙: {len(result['시행규칙'])}개")
    print(f"  PDF_BASE64 신규 다운로드: {base64_new}개")
    print(f"  PDF_BASE64 캐시 재사용: {base64_reused}개")
    if base64_failed:
        print(f"  ⚠️ PDF_BASE64 다운로드 실패: {base64_failed}개")
    print("=" * 60)


if __name__ == "__main__":
    main()
