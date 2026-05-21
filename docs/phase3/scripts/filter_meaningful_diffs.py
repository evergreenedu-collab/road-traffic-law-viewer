"""
조문 연혁 의미 변경 필터 (Stage 7 시제품)
==========================================
text_diff.json 13MB에서 자구·띄어쓰기 변경을 제외하고 "의미 있는 변화"만 추출.

Codex 검증 사전 반영:
  - 절대경로 강제, overnight_phase3 격리
  - 입력은 메인 프로젝트 data/text_diff.json (read-only)
  - 출력은 격리 디렉토리 data/meaningful_diffs.json

휴리스틱 (1차 시제품):
  1. 정규화 (공백·문장부호·한자→한글) 후 동일하면 자구 변경 → 제외
  2. 정규화 후 다르면 의미 변경 후보 → 추출
  3. 추출된 후보에서 단어 추가/삭제 분석 (참고용)

샘플 검증:
  - 제50조 (안전띠): 운전자→전 좌석 변화
  - 제25조 (교차로 우회전): 일시정지 변화
  - 제5조 (어린이보호구역): 민식이법
"""

import json
import re
import sys
import unicodedata
from pathlib import Path
from collections import Counter

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
assert ROOT_DIR.name == "overnight_phase3", f"격리 위반: {ROOT_DIR}"

INPUT_PATH = Path(r"c:\Users\user\projects\도로교통법-한눈에\data\text_diff.json")
# F2 해결: 현행 조문 제목 인덱스 (조문번호 시계열 의미 불일치 차단)
CURRENT_ARTICLES_PATH = Path(
    r"c:\Users\user\projects\도로교통법-한눈에-tutor\tutor\data\index_law_articles.json"
)
OUTPUT_DIR = ROOT_DIR / "data"
OUTPUT_DIR.mkdir(exist_ok=True)
OUTPUT_PATH = OUTPUT_DIR / "meaningful_diffs.json"
SAMPLE_PATH = OUTPUT_DIR / "_diff_samples.json"
EXCLUDED_PATH = OUTPUT_DIR / "_diff_excluded_old_meaning.json"

# 정규화 — 공백, 문장부호, 일반적 한자 표기 차이 제거
PUNCT = re.compile(r'[\s··,.\(\)（）「」『』:;\-‐-―"\'`!?<>\[\]{}/\\]')
# 자주 등장하는 한자 → 한글 (도교법 텍스트에 흔한 것만)
HANJA_KO = {
    "勤勞": "근로", "罰金": "벌금", "罰則": "벌칙", "違反": "위반",
    "免許": "면허", "處罰": "처벌", "處分": "처분", "事項": "사항",
    "義務": "의무", "規定": "규정", "車輛": "차량", "運轉": "운전",
    "運行": "운행", "禁止": "금지", "命令": "명령", "違法": "위법",
    "懲役": "징역", "拘禁刑": "구금형", "保護": "보호", "適用": "적용",
}


def normalize(text):
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    for hanja, ko in HANJA_KO.items():
        s = s.replace(hanja, ko)
    s = PUNCT.sub("", s)
    return s


# F2 — 현행 조문 제목 추출
ARTICLE_TITLE_PATTERNS = [
    re.compile(r'^제[\d의]+조(?:의\d+)?\s*\(([^)]+)\)'),   # 제50조(특정...)
    re.compile(r'^제[\d의]+조(?:의\d+)?\s*([^.\n\r]+)'),    # 괄호 없는 변형
]


def extract_current_title(article_text):
    """index_law_articles 본문에서 현행 조문 제목 추출."""
    if not article_text:
        return None
    first_line = article_text.split("\n", 1)[0].strip()
    for pat in ARTICLE_TITLE_PATTERNS:
        m = pat.match(first_line)
        if m:
            return m.group(1).strip()
    return None


# 한자 → 한글 추가 매핑 (조문 제목 비교용)
TITLE_HANJA_KO = {
    "緊急自動車": "긴급자동차", "優先": "우선", "對": "대", "特例": "특례",
    "道路工事": "도로공사", "申告": "신고",
    "事故發生時": "사고발생시", "措置": "조치", "事故發生": "사고발생",
    "通行區分": "통행구분", "通行": "통행", "優先順位": "우선순위",
    "禁止": "금지", "義務": "의무", "運轉": "운전",
}


def normalize_title(title):
    """조문 제목 정규화 — 공백·괄호·문장부호 제거 + 한자→한글."""
    if not title:
        return ""
    s = title.strip().strip("()")
    s = unicodedata.normalize("NFKC", s)
    for hanja, ko in {**HANJA_KO, **TITLE_HANJA_KO}.items():
        s = s.replace(hanja, ko)
    s = re.sub(r"[\s()（）「」『』·.,\-]", "", s)
    return s


def is_current_meaning(diff_title, current_title):
    """변화의 조문제목이 현행 제목과 같은 의미인지."""
    if not current_title:
        return True   # 현행 제목 모르면 모두 채택 (보수적)
    if not diff_title:
        return False  # 변화에 제목 없으면 의심 → 제외
    return normalize_title(diff_title) == normalize_title(current_title)


def is_jaja_only(prev, after):
    """자구 변경만인지 — 정규화 후 동일하면 True."""
    return normalize(prev) == normalize(after)


def word_diff(prev, after):
    """단어 추가/삭제 분석 — 디버그/연구용."""
    p_tokens = set(re.findall(r"[가-힣a-zA-Z0-9]+", prev or ""))
    a_tokens = set(re.findall(r"[가-힣a-zA-Z0-9]+", after or ""))
    added = sorted(a_tokens - p_tokens)
    removed = sorted(p_tokens - a_tokens)
    return added, removed


def filter_diffs(law_diffs, current_titles=None, group_name=""):
    """한 법령(법률/시행령/시행규칙)의 diff 전체 처리.
    current_titles: {jo: 현행 제목} — F2 시계열 의미 불일치 차단용."""
    out = {}
    excluded = {}   # F2 제외분 (옛 의미)
    stats = Counter()
    current_titles = current_titles or {}
    for jo, revs in law_diffs.items():
        if not isinstance(revs, list):
            continue
        meaningful = []
        old_meaning = []
        current_title = current_titles.get(jo)
        for rev in revs:
            prev = rev.get("이전", "")
            after = rev.get("이후", "")
            change_type = rev.get("변경유형", "")
            rev_title = rev.get("조문제목", "")

            # F2: 현행 의미와 다른 옛 의미 변화는 별도 분리 (학습 콘텐츠에서 제외).
            # 신설·본조신설도 제목 비교 적용 — 옛 조문번호 의미로 신설된 케이스 제외
            # (예: 1961년 신설 "경찰서장의 도로관리자와의 협의"는 옛 50조 의미).
            # current_title 없으면 통과 (보수적).
            if current_title and not is_current_meaning(rev_title, current_title):
                old_meaning.append({
                    "공포일자": rev.get("공포일자"),
                    "변경유형": change_type,
                    "조문제목_옛": rev_title,
                    "조문제목_현행": current_title,
                })
                stats["F2_옛의미_제외"] += 1
                continue

            # 신설·삭제는 항상 의미 변경
            if change_type in ("신설", "삭제"):
                added, removed = word_diff(prev, after)
                meaningful.append({
                    "공포일자": rev.get("공포일자"),
                    "변경유형": change_type,
                    "조문제목": rev.get("조문제목"),
                    "추가단어수": len(added),
                    "삭제단어수": len(removed),
                    "샘플_이전_300": (prev or "")[:300],
                    "샘플_이후_300": (after or "")[:300],
                })
                stats["신설삭제"] += 1
                continue
            # 자구 변경만이면 제외
            if is_jaja_only(prev, after):
                stats["자구변경_제외"] += 1
                continue
            added, removed = word_diff(prev, after)
            # 단어 차이 거의 없으면 (실제 표현 차이만) 제외
            if len(added) + len(removed) <= 2 and abs(len(after) - len(prev)) < 20:
                stats["미세변경_제외"] += 1
                continue
            meaningful.append({
                "공포일자": rev.get("공포일자"),
                "변경유형": change_type,
                "조문제목": rev.get("조문제목"),
                "추가단어수": len(added),
                "삭제단어수": len(removed),
                "주요추가": added[:10],
                "주요삭제": removed[:10],
                "샘플_이전_300": (prev or "")[:300],
                "샘플_이후_300": (after or "")[:300],
            })
            stats["의미변경_채택"] += 1
        if meaningful:
            out[jo] = meaningful
        if old_meaning:
            excluded[jo] = old_meaning
    return out, excluded, stats


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if not INPUT_PATH.exists():
        print(f"[ERR] input not found: {INPUT_PATH}", flush=True)
        sys.exit(1)
    print(f"[READ] {INPUT_PATH} ({INPUT_PATH.stat().st_size / 1024 / 1024:.1f}MB)", flush=True)
    data = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    print(f"  top-level: {list(data.keys())}", flush=True)

    # F2 — 현행 조문 제목 인덱스 로드 (법률만 적용 — 시행령·시행규칙은 별도 인덱스 필요)
    current_titles_law = {}
    if CURRENT_ARTICLES_PATH.exists():
        arts = json.loads(CURRENT_ARTICLES_PATH.read_text(encoding="utf-8")).get("조문별", {})
        for jo, text in arts.items():
            t = extract_current_title(text)
            if t:
                current_titles_law[jo] = t
        print(f"  현행 조문 제목 인덱스(법률): {len(current_titles_law)}개", flush=True)

    result = {"_생성_시각_기준": data.get("생성일시", ""), "법률": {}, "시행령": {}, "시행규칙": {}}
    excluded_all = {}
    total_stats = Counter()
    for group in ("법률", "시행령", "시행규칙"):
        if group not in data:
            continue
        print(f"\n[FILTER] {group}", flush=True)
        titles = current_titles_law if group == "법률" else None
        diffs, excluded, stats = filter_diffs(data[group], titles, group)
        result[group] = diffs
        excluded_all[group] = excluded
        for k, v in stats.items():
            total_stats[k] += v
        print(f"  통계: {dict(stats)}", flush=True)

    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    EXCLUDED_PATH.write_text(json.dumps(excluded_all, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[SAVE] {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size / 1024:.0f}KB)", flush=True)
    print(f"[SAVE] {EXCLUDED_PATH.name} (F2 옛 의미 제외분)", flush=True)
    print(f"[TOTAL] {dict(total_stats)}", flush=True)

    # 샘플 검증 — 안전띠(50), 교차로 우회전(25), 어린이보호구역 관련(12, 12의2)
    samples = {}
    for jo in ["50", "25", "12", "12의2", "44", "5의3"]:
        # 법률에서 조문 검색 (도교법 단위)
        if jo in result["법률"]:
            samples[f"법률 제{jo}조"] = result["법률"][jo]
    SAMPLE_PATH.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SAMPLE] {SAMPLE_PATH}", flush=True)
    print(f"  샘플 조문 발견: {list(samples.keys())}", flush=True)


if __name__ == "__main__":
    main()
