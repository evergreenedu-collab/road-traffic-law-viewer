"""
별표 PDF 증분 다운로드
========================
attached_tables_diff.json의 변경 시점 PDF URL을 따라가서
data/table_pdfs/{법령유형}_{별표명}_{공포일자}.pdf 형식으로 저장한다.
이미 있는 파일은 건너뛰어, 자동 업데이트 시 신규 시점만 받는다.

사용법:
    python download_table_pdfs.py

출력:
    data/table_pdfs/시행규칙_별표 28_20180928.pdf  ...
"""

import json
import os
import re
import time

import requests

REQUEST_DELAY = 0.4  # 다운로드 간격
TIMEOUT = 60

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
DIFF_PATH = os.path.join(DATA_DIR, "attached_tables_diff.json")
PDF_DIR = os.path.join(DATA_DIR, "table_pdfs")
BASE_URL = "https://www.law.go.kr"


def safe_filename(s):
    """파일시스템 안전한 이름으로 변환 (공백 → _)"""
    return re.sub(r'[\\/:*?"<>|]', "_", s).replace(" ", "_")


def pdf_filename(law_type, table_name, pub_date):
    """PDF 파일명 규칙: 시행규칙_별표28_20180928.pdf"""
    return f"{safe_filename(law_type)}_{safe_filename(table_name)}_{pub_date}.pdf"


def collect_targets():
    """다운로드 대상 (법령유형, 별표명, 공포일자, PDF_URL) 추출"""
    if not os.path.exists(DIFF_PATH):
        raise FileNotFoundError(f"{DIFF_PATH} 없음. build_attached_tables_diff.py 먼저 실행.")
    with open(DIFF_PATH, "r", encoding="utf-8") as f:
        diff = json.load(f)
    targets = []
    seen = set()  # (법령유형, 별표명, 공포일자) 중복 제거
    for law_type in ["시행령", "시행규칙"]:
        for tname, changes in diff.get(law_type, {}).items():
            if not tname.startswith("별표"):
                continue  # 서식/별지는 제외
            for ch in changes:
                # 직전 + 직후 양쪽 PDF 다 받음
                for pub_key, url_key in [("이전공포일", "이전PDF_URL"), ("공포일자", "이후PDF_URL")]:
                    pub = ch.get(pub_key, "")
                    url = ch.get(url_key, "")
                    if not pub or not url:
                        continue
                    key = (law_type, tname, pub)
                    if key in seen:
                        continue
                    seen.add(key)
                    targets.append((law_type, tname, pub, url))
    return targets


def main():
    print("=" * 60)
    print("  별표 PDF 증분 다운로드")
    print("=" * 60)

    os.makedirs(PDF_DIR, exist_ok=True)
    targets = collect_targets()
    print(f"\n📋 다운로드 대상 {len(targets)}건 (변경 시점의 직전·직후 PDF)")

    existing = 0
    downloaded = 0
    failed = 0
    skipped_no_url = 0

    for i, (law_type, tname, pub, url) in enumerate(targets):
        fname = pdf_filename(law_type, tname, pub)
        fpath = os.path.join(PDF_DIR, fname)
        if os.path.exists(fpath) and os.path.getsize(fpath) > 0:
            existing += 1
            continue

        full_url = BASE_URL + url
        try:
            time.sleep(REQUEST_DELAY)
            r = requests.get(full_url, timeout=TIMEOUT, stream=True)
            if r.status_code == 200:
                with open(fpath, "wb") as f:
                    for chunk in r.iter_content(8192):
                        if chunk:
                            f.write(chunk)
                downloaded += 1
                if downloaded % 50 == 0:
                    print(f"  [{i+1}/{len(targets)}] 다운로드 {downloaded}건 (기존 {existing}, 실패 {failed})")
            else:
                failed += 1
                print(f"  ❌ HTTP {r.status_code}: {fname}")
        except Exception as e:
            failed += 1
            print(f"  ❌ 오류: {fname} — {e}")

    # 결과
    total_size = sum(
        os.path.getsize(os.path.join(PDF_DIR, f))
        for f in os.listdir(PDF_DIR)
        if f.endswith(".pdf")
    )
    print(f"\n📊 결과")
    print(f"  신규 다운로드: {downloaded}건")
    print(f"  기존 (건너뜀): {existing}건")
    print(f"  실패: {failed}건")
    print(f"  PDF 폴더 총 크기: {total_size/1024/1024:.1f}MB")
    print(f"  저장 위치: {PDF_DIR}")


if __name__ == "__main__":
    main()
