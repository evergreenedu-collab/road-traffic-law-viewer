"""
도로교통법 개정 연혁 추적기 - 데이터 수집 스크립트
=================================================
국가법령정보 오픈API를 활용하여 특정 조문의 개정 이력을 수집합니다.

사용법:
    python law_history_collector.py --article 73 --output result.json
    python law_history_collector.py --article 73 --output result.json --include-sub-laws

필요 패키지:
    pip install requests

API 키: evergreen_edu (국가법령정보 공동활용)
"""

import requests
import xml.etree.ElementTree as ET
import json
import os
import time
import argparse
import re
from datetime import datetime
from typing import Optional


# === 설정 ===
API_KEY = "evergreen_edu"  # 국가법령정보 오픈API 키
SEARCH_URL = "http://www.law.go.kr/DRF/lawSearch.do"
DETAIL_URL = "http://www.law.go.kr/DRF/lawService.do"
REQUEST_DELAY = 0.6  # API 요청 간격 (초)

# 도로교통법 관련 법령 그룹
LAW_GROUP = {
    "법률": "도로교통법",
    "시행령": "도로교통법 시행령",
    "시행규칙": "도로교통법 시행규칙",
}


def safe_text(element, tag: str) -> str:
    """XML 요소에서 안전하게 텍스트 추출"""
    el = element.find(tag)
    if el is not None and el.text:
        return el.text.strip()
    return ""


def safe_attr(element, attr: str) -> str:
    """XML 요소에서 안전하게 속성 추출"""
    return element.get(attr, "").strip()


def search_law_history(law_name: str) -> list[dict]:
    """
    법령명으로 연혁 목록을 검색합니다.
    반환: [{법령ID, 법령명, 공포일자, 공포번호, 시행일자, 제개정구분, 법령MST}, ...]
    """
    print(f"\n📋 [{law_name}] 연혁 목록 검색 중...")
    all_items = []
    page = 1

    while True:
        params = {
            "OC": API_KEY,
            "target": "law",
            "type": "XML",
            "query": law_name,
            "display": 100,
            "page": page,
        }
        try:
            resp = requests.get(SEARCH_URL, params=params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  ❌ API 요청 실패: {e}")
            break

        root = ET.fromstring(resp.text)

        # 전체 건수 확인
        total_cnt = int(safe_text(root, "totalCnt") or "0")
        if total_cnt == 0:
            print(f"  ⚠️ 검색 결과 없음")
            break

        # 법령 항목 파싱
        items = root.findall(".//law") or root.findall(".//법령")
        if not items:
            # XML 태그명이 다를 수 있으므로 직접 탐색
            items = [el for el in root if el.tag not in (
                "totalCnt", "page", "nwRvsn", "상태"
            )]

        for item in items:
            law_nm = safe_text(item, "법령명한글") or safe_text(item, "법령명_한글")
            if not law_nm:
                law_nm = safe_text(item, "법령명")

            # 정확히 해당 법령만 필터링 (예: "도로교통법"인데 "도로교통법 시행령"은 제외)
            if law_nm != law_name:
                continue

            entry = {
                "법령명": law_nm,
                "법령ID": safe_text(item, "법령ID") or safe_attr(item, "법령키"),
                "MST": safe_text(item, "법령MST") or safe_text(item, "법령일련번호"),
                "공포일자": safe_text(item, "공포일자"),
                "공포번호": safe_text(item, "공포번호"),
                "시행일자": safe_text(item, "시행일자"),
                "제개정구분": safe_text(item, "제개정구분"),
                "법종구분": safe_text(item, "법종구분"),
                "소관부처": safe_text(item, "소관부처"),
            }
            all_items.append(entry)

        # 페이지네이션 확인
        if page * 100 >= total_cnt:
            break
        page += 1
        time.sleep(REQUEST_DELAY)

    print(f"  ✅ {len(all_items)}건 발견")
    return sorted(all_items, key=lambda x: x.get("공포일자", ""), reverse=True)


def fetch_law_detail(mst_or_id: str) -> Optional[dict]:
    """
    법령 본문을 가져와서 조문, 부칙, 제개정이유를 파싱합니다.
    """
    params = {
        "OC": API_KEY,
        "target": "law",
        "type": "XML",
        "MST": mst_or_id,
    }
    try:
        resp = requests.get(DETAIL_URL, params=params, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    ❌ 본문 조회 실패 (MST={mst_or_id}): {e}")
        return None

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        # MST가 아닌 법령ID로 재시도
        params_alt = {
            "OC": API_KEY,
            "target": "law",
            "type": "XML",
            "ID": mst_or_id,
        }
        try:
            resp = requests.get(DETAIL_URL, params=params_alt, timeout=60)
            root = ET.fromstring(resp.text)
        except Exception:
            print(f"    ❌ XML 파싱 실패 (MST={mst_or_id})")
            return None

    # === 기본정보 추출 ===
    basic = root.find(".//기본정보") or root
    info = {
        "법령명": safe_text(basic, "법령명_한글") or safe_text(basic, "법령명한글"),
        "법령ID": safe_text(basic, "법령ID"),
        "공포일자": safe_text(basic, "공포일자"),
        "공포번호": safe_text(basic, "공포번호"),
        "시행일자": safe_text(basic, "시행일자"),
        "제개정구분": safe_text(basic, "제개정구분"),
        "소관부처": safe_text(basic, "소관부처"),
    }

    # === 조문 추출 ===
    articles = []
    for jo in root.findall(".//조문단위"):
        article = {
            "조문번호": safe_text(jo, "조문번호"),
            "조문가지번호": safe_text(jo, "조문가지번호"),
            "조문제목": safe_text(jo, "조문제목"),
            "조문시행일자": safe_text(jo, "조문시행일자"),
            "조문제개정유형": safe_text(jo, "조문제개정유형"),
            "조문변경여부": safe_text(jo, "조문변경여부"),
            "조문내용": safe_text(jo, "조문내용"),
            "항목": [],
        }
        # 항 추출
        for hang in jo.findall(".//항"):
            h = {
                "항번호": safe_text(hang, "항번호"),
                "항내용": safe_text(hang, "항내용"),
                "항제개정유형": safe_text(hang, "항제개정유형"),
                "호목": [],
            }
            for ho in hang.findall(".//호"):
                h["호목"].append({
                    "호번호": safe_text(ho, "호번호"),
                    "호내용": safe_text(ho, "호내용"),
                })
            article["항목"].append(h)
        articles.append(article)
    info["조문"] = articles

    # === 부칙 추출 ===
    addenda = []
    for bk in root.findall(".//부칙단위"):
        addenda.append({
            "부칙공포일자": safe_text(bk, "부칙공포일자"),
            "부칙공포번호": safe_text(bk, "부칙공포번호"),
            "부칙내용": safe_text(bk, "부칙내용"),
        })
    info["부칙"] = addenda

    # === 제개정이유 추출 ===
    reason = safe_text(root, "제개정이유내용")
    if not reason:
        reason_el = root.find(".//제개정이유")
        if reason_el is not None:
            reason = safe_text(reason_el, "제개정이유내용") or (reason_el.text or "").strip()
    info["제개정이유"] = reason

    # === 개정문 추출 ===
    amend_text = safe_text(root, "개정문내용")
    if not amend_text:
        amend_el = root.find(".//개정문")
        if amend_el is not None:
            amend_text = safe_text(amend_el, "개정문내용") or (amend_el.text or "").strip()
    info["개정문"] = amend_text

    return info


def extract_article_changes(
    law_detail: dict,
    target_article: int,
    target_sub: Optional[int] = None
) -> Optional[dict]:
    """
    특정 조문(예: 73조)의 변경 내용을 추출합니다.

    Args:
        law_detail: fetch_law_detail()의 반환값
        target_article: 조문 번호 (예: 73)
        target_sub: 조문 가지번호 (예: 73조의2 → 2)
    """
    for article in law_detail.get("조문", []):
        jo_num = article.get("조문번호", "").strip()
        jo_sub = article.get("조문가지번호", "").strip()

        # 조문번호 매칭
        try:
            if int(jo_num) != target_article:
                continue
        except (ValueError, TypeError):
            continue

        # 가지번호 매칭 (73조의2 등)
        if target_sub is not None:
            try:
                if int(jo_sub) != target_sub:
                    continue
            except (ValueError, TypeError):
                continue
        else:
            if jo_sub and jo_sub != "0":
                continue

        return {
            "조문번호": jo_num,
            "조문가지번호": jo_sub,
            "조문제목": article.get("조문제목", ""),
            "조문시행일자": article.get("조문시행일자", ""),
            "조문제개정유형": article.get("조문제개정유형", ""),
            "조문내용": article.get("조문내용", ""),
            "항목": article.get("항목", []),
        }
    return None


def find_effective_date_from_addenda(addenda: list, target_article: int) -> str:
    """
    부칙에서 특정 조문의 실제 시행일자를 찾습니다.
    부칙에 별도 시행일 규정이 있으면 그걸, 없으면 빈 문자열을 반환합니다.
    """
    for bk in addenda:
        content = bk.get("부칙내용", "")
        # "제73조"가 부칙에 명시적으로 언급된 경우 해당 시행일 추출 시도
        pattern = rf"제{target_article}조.*?(\d{{4}})년\s*(\d{{1,2}})월\s*(\d{{1,2}})일.*?시행"
        match = re.search(pattern, content)
        if match:
            y, m, d = match.groups()
            return f"{y}{int(m):02d}{int(d):02d}"
    return ""


def format_date(date_str: str) -> str:
    """'20180327' → '2018.03.27' 형식으로 변환"""
    if len(date_str) == 8:
        return f"{date_str[:4]}.{date_str[4:6]}.{date_str[6:]}"
    return date_str


def build_amendment_timeline(
    target_article: int,
    target_sub: Optional[int] = None,
    include_sub_laws: bool = True,
    max_versions: int = 50,
) -> dict:
    """
    메인 함수: 특정 조문의 개정 연혁 타임라인을 구축합니다.

    Args:
        target_article: 추적할 조문 번호 (예: 73)
        target_sub: 가지번호 (예: 73조의2 → 2), 없으면 None
        include_sub_laws: 시행령/시행규칙도 포함할지
        max_versions: 최대 조회할 연혁 수

    Returns:
        구조화된 타임라인 딕셔너리
    """
    article_label = f"제{target_article}조" + (f"의{target_sub}" if target_sub else "")
    print(f"\n{'='*60}")
    print(f"🔍 {article_label} 개정 연혁 추적 시작")
    print(f"{'='*60}")

    # 조회할 법령 목록 결정
    laws_to_check = {"법률": LAW_GROUP["법률"]}
    if include_sub_laws:
        laws_to_check.update({
            "시행령": LAW_GROUP["시행령"],
            "시행규칙": LAW_GROUP["시행규칙"],
        })

    timeline = {
        "조문": article_label,
        "생성일시": datetime.now().isoformat(),
        "법령그룹": [],
    }

    for law_type, law_name in laws_to_check.items():
        print(f"\n{'─'*40}")
        print(f"📖 {law_type}: {law_name}")
        print(f"{'─'*40}")

        # 1단계: 연혁 목록 검색
        history = search_law_history(law_name)
        if not history:
            continue

        # 최근 N건만 처리
        history = history[:max_versions]

        law_changes = {
            "법령유형": law_type,
            "법령명": law_name,
            "전체연혁수": len(history),
            "개정이력": [],
        }

        # 2단계: 각 연혁 버전의 본문 조회
        for i, ver in enumerate(history):
            mst = ver.get("MST") or ver.get("법령ID")
            if not mst:
                continue

            print(f"  📄 [{i+1}/{len(history)}] {ver.get('공포일자', '?')} "
                  f"({ver.get('제개정구분', '?')}) 조회 중...")
            time.sleep(REQUEST_DELAY)

            detail = fetch_law_detail(mst)
            if not detail:
                continue

            # 3단계: 해당 조문 추출
            article_data = extract_article_changes(detail, target_article, target_sub)

            # 4단계: 부칙에서 실제 시행일 확인
            addenda_date = find_effective_date_from_addenda(
                detail.get("부칙", []), target_article
            )

            change_entry = {
                "공포일자": detail.get("공포일자", ""),
                "공포번호": detail.get("공포번호", ""),
                "법령시행일자": detail.get("시행일자", ""),
                "제개정구분": detail.get("제개정구분", ""),
                "부칙별도시행일": addenda_date,
                "제개정이유": detail.get("제개정이유", ""),
                "개정문요약": detail.get("개정문", "")[:500] if detail.get("개정문") else "",
            }

            if article_data:
                change_entry["조문존재"] = True
                change_entry["조문제목"] = article_data.get("조문제목", "")
                change_entry["조문시행일자"] = article_data.get("조문시행일자", "")
                change_entry["조문제개정유형"] = article_data.get("조문제개정유형", "")
                change_entry["조문내용"] = article_data.get("조문내용", "")
                change_entry["항목"] = article_data.get("항목", [])
            else:
                change_entry["조문존재"] = False

            # 부칙 내용 중 해당 조문 관련 부분만 저장
            relevant_addenda = []
            for bk in detail.get("부칙", []):
                content = bk.get("부칙내용", "")
                if (f"제{target_article}조" in content or
                    "시행일" in content or
                    "경과조치" in content):
                    relevant_addenda.append({
                        "부칙공포일자": bk.get("부칙공포일자", ""),
                        "부칙내용": content[:1000],  # 길이 제한
                    })
            change_entry["관련부칙"] = relevant_addenda

            law_changes["개정이력"].append(change_entry)

        # 조문이 실제로 변경된 이력만 필터링
        changed_versions = [
            e for e in law_changes["개정이력"]
            if e.get("조문존재") and e.get("조문제개정유형")
        ]
        law_changes["조문변경이력수"] = len(changed_versions)

        timeline["법령그룹"].append(law_changes)

    return timeline


def save_results(data: dict, output_path: str):
    """결과를 JSON 파일로 저장"""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n💾 결과 저장 완료: {output_path}")


def save_markdown_summary(data: dict, output_path: str):
    """결과를 마크다운 요약 파일로 저장 (Claude Project 업로드용)"""
    # docs/ 폴더에 저장
    base_name = os.path.basename(output_path).replace(".json", "_summary.md")
    docs_dir = os.path.join(os.path.dirname(os.path.dirname(output_path) or "."), "docs")
    if not os.path.isdir(docs_dir):
        docs_dir = "docs"
    os.makedirs(docs_dir, exist_ok=True)
    md_path = os.path.join(docs_dir, base_name)

    lines = []
    article = data.get("조문", "")
    lines.append(f"# 도로교통법 {article} 개정 연혁 추적 결과\n")
    lines.append(f"생성일시: {data.get('생성일시', '')}\n")

    for group in data.get("법령그룹", []):
        law_type = group.get("법령유형", "")
        law_name = group.get("법령명", "")
        lines.append(f"\n## {law_type}: {law_name}\n")
        lines.append(f"전체 연혁 수: {group.get('전체연혁수', 0)}건 / "
                      f"해당 조문 변경: {group.get('조문변경이력수', 0)}건\n")

        # 변경 이력 표
        lines.append("\n| 구분 | 공포일 | 시행일 | 조문시행일 | 부칙별도시행일 | 제개정유형 |")
        lines.append("|------|--------|--------|-----------|--------------|-----------|")

        for entry in group.get("개정이력", []):
            if not entry.get("조문존재"):
                continue
            row = (
                f"| {entry.get('제개정구분', '')} "
                f"| {format_date(entry.get('공포일자', ''))} "
                f"| {format_date(entry.get('법령시행일자', ''))} "
                f"| {format_date(entry.get('조문시행일자', ''))} "
                f"| {format_date(entry.get('부칙별도시행일', ''))} "
                f"| {entry.get('조문제개정유형', '')} |"
            )
            lines.append(row)

        # 상세 내용
        lines.append(f"\n### 개정 상세 내용\n")
        for entry in group.get("개정이력", []):
            if not entry.get("조문존재"):
                continue
            if not entry.get("조문제개정유형"):
                continue

            pub_date = format_date(entry.get("공포일자", ""))
            lines.append(f"\n#### {pub_date} ({entry.get('제개정구분', '')})\n")

            # 시행일 정보
            eff_date = format_date(entry.get("법령시행일자", ""))
            jo_eff = format_date(entry.get("조문시행일자", ""))
            bk_eff = format_date(entry.get("부칙별도시행일", ""))

            lines.append(f"- **공포일**: {pub_date}")
            lines.append(f"- **법령 시행일**: {eff_date}")
            if jo_eff:
                lines.append(f"- **조문 시행일**: {jo_eff}")
            if bk_eff:
                lines.append(f"- **부칙 별도 시행일**: {bk_eff}")
            lines.append(f"- **조문 제개정유형**: {entry.get('조문제개정유형', '')}")
            lines.append(f"- **조문 제목**: {entry.get('조문제목', '')}\n")

            # 조문 내용
            content = entry.get("조문내용", "")
            if content:
                lines.append(f"**조문 내용:**\n```\n{content[:2000]}\n```\n")

            # 제개정이유
            reason = entry.get("제개정이유", "")
            if reason:
                lines.append(f"**제개정이유:**\n{reason[:3000]}\n")

            # 관련 부칙
            addenda = entry.get("관련부칙", [])
            if addenda:
                lines.append(f"**관련 부칙:**")
                for bk in addenda:
                    lines.append(f"```\n{bk.get('부칙내용', '')[:1000]}\n```")

        lines.append("\n---\n")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"📝 마크다운 요약 저장 완료: {md_path}")


def parse_article_input(article_str: str) -> tuple[int, Optional[int]]:
    """
    '73' → (73, None)
    '73의2' → (73, 2)
    '148-2' → (148, 2)
    """
    # "73의2" 패턴
    match = re.match(r"(\d+)의(\d+)", article_str)
    if match:
        return int(match.group(1)), int(match.group(2))
    # "148-2" 패턴
    match = re.match(r"(\d+)-(\d+)", article_str)
    if match:
        return int(match.group(1)), int(match.group(2))
    # 단순 숫자
    return int(article_str), None


def main():
    parser = argparse.ArgumentParser(
        description="도로교통법 개정 연혁 추적기",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python law_history_collector.py --article 73
  python law_history_collector.py --article 73의2
  python law_history_collector.py --article 148 --include-sub-laws
  python law_history_collector.py --article 73 --max-versions 30
        """
    )
    parser.add_argument(
        "--article", "-a",
        required=True,
        help="추적할 조문 번호 (예: 73, 73의2, 148)"
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="출력 파일 경로 (기본: article_73_history.json)"
    )
    parser.add_argument(
        "--include-sub-laws", "-s",
        action="store_true",
        default=False,
        help="시행령/시행규칙도 포함하여 조회"
    )
    parser.add_argument(
        "--max-versions", "-m",
        type=int,
        default=50,
        help="최대 조회할 연혁 수 (기본: 50)"
    )
    args = parser.parse_args()

    # 조문 번호 파싱
    target_article, target_sub = parse_article_input(args.article)
    article_label = f"{target_article}" + (f"의{target_sub}" if target_sub else "")

    # 출력 파일명 결정 (data/ 폴더에 자동 저장)
    if args.output:
        output = args.output
    else:
        os.makedirs("data", exist_ok=True)
        os.makedirs("docs", exist_ok=True)
        output = os.path.join("data", f"article_{article_label}_history.json")

    print(f"""
╔══════════════════════════════════════════════╗
║   도로교통법 개정 연혁 추적기                    ║
║   대상 조문: 제{article_label}조                ║
║   하위법령 포함: {'예' if args.include_sub_laws else '아니오'}                        ║
╚══════════════════════════════════════════════╝
    """)

    # 타임라인 구축
    timeline = build_amendment_timeline(
        target_article=target_article,
        target_sub=target_sub,
        include_sub_laws=args.include_sub_laws,
        max_versions=args.max_versions,
    )

    # 결과 저장
    save_results(timeline, output)
    save_markdown_summary(timeline, output)

    # 간단 통계 출력
    print(f"\n{'='*60}")
    print("📊 수집 결과 요약")
    print(f"{'='*60}")
    for group in timeline.get("법령그룹", []):
        law_type = group.get("법령유형", "")
        total = group.get("전체연혁수", 0)
        changed = group.get("조문변경이력수", 0)
        print(f"  {law_type}: 전체 {total}건 중 해당 조문 변경 {changed}건")

    print(f"\n✅ 완료! 결과 파일:")
    print(f"  - JSON: {output}")
    print(f"  - 마크다운: {output.replace('.json', '_summary.md')}")
    print(f"\n💡 마크다운 파일을 Claude Project에 업로드하면")
    print(f"   개정 연혁 질의응답이 가능합니다.")


if __name__ == "__main__":
    main()
