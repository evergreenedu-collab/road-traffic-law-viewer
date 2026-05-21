"""
출근길 법령 튜터 — 원본 PDF 재추출 (R11)
=====================================================
해설집·수사실무·사고조사판례집의 .md 자료는 기존 PDF→마크다운 변환기가
표·읽기순서를 망가뜨려 가독성이 크게 떨어졌다. 이 스크립트는 원본 PDF를
PyMuPDF(fitz)로 직접 재추출해 깨끗한 .md를 생성한다.

추출 원리:
  - PDF 줄(line) 단위로 좌표·폰트와 함께 수집 → (y, x)로 정렬해 읽기순서 보존
  - 수직 간격으로 단락을 재구성, 줄을 결합 (fitz가 단어 경계 공백을 보존하므로
    PDF 줄바꿈으로 깨진 문장이 올바르게 이어붙음)
  - 상단/하단 여백의 러닝헤더·페이지번호, 목차 점선(······) 제거
  - topic_doc는 폰트 크기로 마크다운 헤더(절·항목) 복원
  - law_comment는 '제N조(제목)' 헤더가 독립 줄로 유지되게 함 (build_indexes 인식)

수동 실행. 출력 .md를 검토 후 sources_config.json의 source_dir로 옮기고
build_indexes.py를 재실행하면 인덱스에 반영된다.

  py tutor/extract_pdf_sources.py
"""

import re
import sys
from collections import Counter
from pathlib import Path

import fitz  # PyMuPDF

PDF_DIR = Path(r"C:\Users\user\projects\판례조회-AI도구\판례모음\참고 pdf 파일")
OUT_DIR = Path(r"C:\Users\user\projects\판례조회-AI도구\_재추출")

SOURCES = [
    {
        "pdf": "알기쉬운 도로교통법 해설(23년).pdf",
        "kind": "law_comment",
        "out": "2024년 도로교통법해설.md",
        "head": ("# KoRoad 도로교통법 해설\n"
                 "## 출처: 경찰청 알기쉬운 도로교통법 해설(2023)\n"
                 "## 활용: 교통안전교육 참고자료 (법적 효력 없음, 반드시 현행 법령 확인)"),
    },
    {
        "pdf": "교통범죄수사실무연구(충남경찰청).pdf",
        "kind": "topic_doc",
        "out": "2021년 교통범죄수사실무연구.md",
        "head": ("# KoRoad 교통범죄 수사실무연구\n"
                 "## 출처: 충남경찰청 교통범죄수사실무연구(2021)"),
    },
    {
        "pdf": "교통사고조사판례집(경찰청).pdf",
        "kind": "topic_doc",
        "out": "2012년 교통사고조사판례집.md",
        "head": ("# KoRoad 교통사고 조사판례집\n"
                 "## 출처: 경찰청 교통사고조사판례집(2012)"),
    },
]

# 해설집 '제N조(제목)' 헤더 줄 — 닫는 괄호 뒤에 본문이 없는 순수 헤더만
ARTICLE_LINE = re.compile(r'제\s*\d+\s*조(?:의\s*\d+)?\s*\([^)]+\)\s*$')
# 목차 점선 (······, .......)
DOT_LEADER = re.compile(r'[·.…]{4,}')
# topic_doc 하위 헤더 패턴 (절·장·번호·가나다·동그라미숫자)
SUBHEAD_PAT = re.compile(r'^(제\s*\d+\s*[절장]\b|\d{1,2}\.\s|[가-하]\.\s|[①-⑮])')
# 제목 없이 '제N절'·'제N장'만 있는 헤더 (PDF에서 다음 줄에 제목이 분리됨)
BARE_HEAD = re.compile(r'^#+\s*제\s*\d+\s*[절장]\s*$')
# 문장 종료 표시 (단락 경계 판정)
SENT_TERM = ('.', '?', '!', '」', '”', '’', ')', ']', ':', '．', '。')
# 번호·기호 항목 — 별도 단락으로 시작시킴 (R12-B: 조문 원문 목록 가독성).
# 줄 시작의 'N. '·'가. '·'①' 등. 본문 문장은 'N. '로 시작하지 않으므로 안전.
LIST_MARKER = re.compile(r'^(?:\d{1,2}[.)]\s|[가-하][.)]\s|[①-⑳])')
# 그림 캡션('그림 N-N')이 본문 문장 끝에 붙어 가독성을 해침 (R13-D).
# PDF 이미지 인셋이 읽기순서로 본문에 끼어드는 구조적 문제라 완벽 분리는 불가하나,
# 캡션 앞에서 줄을 나눠 본문 문장만은 깨끗하게 떼어낸다.
# 캡션 마커 직후가 '조사로 끝나는 어절'(예: '그림 4-24를 보면')이면 본문 참조이므로
# 분리하지 않는다 (Codex 반영). '도로'의 '도'처럼 조사 글자로 시작하는 명사는
# 조사 뒤 경계(공백·구두점·끝) 조건으로 걸러져 캡션으로 정상 처리된다.
# 둘째 숫자 뒤 (?!\d) — 조사 lookahead 회피용 백트래킹이 '4-24'를 '4-2'로 쪼개는 것 차단.
FIGURE_CAPTION = re.compile(
    r'\s*(그림\s*\d+\s*[-－–~]\s*\d+(?!\d))\s*'
    r'(?!(?:을|를|이|가|은|는|와|과|의|에|에서|에게|으로|로|도|만|까지|처럼|보다)'
    r'(?=[\s,.)\]」』]|$))')
# 인라인 각주번호 — 한글/닫는괄호 바로 뒤(공백 없이) 1~3자리 숫자 + ')'.
# 본문·캡션에 박힌 각주 참조 표기로, 그림 없는 .md에서는 잡음일 뿐 (R14-2).
# 공백 없이 붙은 것만 — '다음 1)' 같은 번호 항목 오삭제 방지 (Codex 반영).
INLINE_FOOTNOTE = re.compile(r'(?<=[가-힣)])\d{1,3}\)')
# 그림 캡션으로 시작하는 줄 — 캡션 번호 뒤가 조사면(본문 참조 '그림 4-24를') 제외 (Codex 반영)
FIG_LINE = re.compile(
    r'^그림\s*\d+\s*[-－–~]\s*\d+(?!\d)\s*'
    r'(?!(?:을|를|이|가|은|는|와|과|의|에|에서|에게|으로|로|도|만|까지|처럼|보다)(?=[\s,.)\]」』]|$))')


def split_figure_caption_lines(para):
    """그림 캡션 줄에서 캡션 제목과 그 뒤 본문을 분리하고 인라인 각주번호를 제거 (R14-2).
    캡션 줄에 인라인 각주번호가 있으면 그 위치를 캡션|본문 경계로 본다 — PDF에서
    캡션 뒤에 본문이 이어붙는 구조 대응. 캡션이 괄호 미완으로 다음 줄까지 쪼개진
    경우(R15-3) 다음 줄을 병합한 뒤 분리한다. 경계 신호가 없으면 분리 못 함(한계)."""
    fixed = []
    lines = para.split('\n')
    i = 0
    while i < len(lines):
        ln = lines[i]
        if FIG_LINE.match(ln):
            # R15-3: 캡션이 괄호 미완('(' 수 > ')' 수)이면 PDF 줄바꿈으로 쪼개진
            # 것 — 닫는 괄호가 나올 때까지 다음 줄을 병합(최대 2줄 — OCR로 괄호가
            # 안 닫히면 본문을 통째로 흡수하지 않게, Codex 반영).
            merged = 0
            while (ln.count('(') > ln.count(')')
                   and i + 1 < len(lines) and merged < 2):
                i += 1
                ln += ' ' + lines[i].lstrip()
                merged += 1
            fm = INLINE_FOOTNOTE.search(ln)
            if fm:
                cap = ln[:fm.start()].rstrip()
                rest = ln[fm.end():].lstrip()
                if cap:
                    fixed.append(cap)
                if rest:
                    fixed.append(rest)
                i += 1
                continue
        fixed.append(INLINE_FOOTNOTE.sub('', ln))
        i += 1
    return '\n'.join(fixed)


def doc_lines(page):
    """페이지 → [(y0, x0, raw_text, size)] 줄 리스트.
    러닝헤더·페이지번호·목차점선 제거. raw_text는 줄 끝 공백을 보존(단어결합용)."""
    h = page.rect.height
    rows = []
    for blk in page.get_text("dict")["blocks"]:
        for ln in blk.get("lines", []):
            raw = "".join(sp["text"] for sp in ln["spans"])
            stripped = re.sub(r"\s+", " ", raw).strip()
            if not stripped:
                continue
            size = max((sp["size"] for sp in ln["spans"] if sp["text"].strip()),
                       default=0.0)
            y0, x0 = ln["bbox"][1], ln["bbox"][0]
            if DOT_LEADER.search(stripped):                  # 목차 점선
                continue
            # 페이지번호·러닝헤더는 상단/하단 여백에 있을 때만 제거 —
            # 본문 속 숫자만 있는 줄(표 셀·날짜 등)이 잘못 삭제되는 것 방지
            in_margin = y0 < h * 0.085 or y0 > h * 0.90
            is_page_num = re.fullmatch(r"[\d\s.\-]+", stripped) is not None
            if in_margin and (is_page_num or len(stripped) < 50):
                continue
            rows.append((y0, x0, raw, size))
    rows.sort(key=lambda r: (round(r[0]), r[1]))
    return rows


def global_line_height(doc):
    """문서 전체에서 가장 흔한 줄 간격 = 본문 줄 높이."""
    gaps = Counter()
    step = max(1, doc.page_count // 60)
    for pi in range(0, doc.page_count, step):
        ys = sorted(r[0] for r in doc_lines(doc[pi]))
        for a, b in zip(ys, ys[1:]):
            g = round(b - a)
            if 8 <= g <= 40:
                gaps[g] += 1
    return gaps.most_common(1)[0][0] if gaps else 18


def body_font(doc):
    """가장 흔한 폰트 크기(글자수 가중) = 본문 크기."""
    cnt = Counter()
    step = max(1, doc.page_count // 80)
    for pi in range(0, doc.page_count, step):
        for blk in doc[pi].get_text("dict")["blocks"]:
            for ln in blk.get("lines", []):
                for sp in ln["spans"]:
                    t = sp["text"].strip()
                    if t:
                        cnt[round(sp["size"], 1)] += len(t)
    return cnt.most_common(1)[0][0] if cnt else 10.0


def extract(doc, kind, body, lh):
    """PDF → 단락/헤더 문자열 리스트."""
    out = []
    buf = []          # 현재 단락의 줄들 (줄 끝 공백 보존)
    buf_size = [0.0]
    thr = lh * 1.4
    prev_y = [None]

    def flush():
        if buf:
            para = re.sub(r"[ \t]+", " ", "".join(buf)).strip()
            # 해설집 각주(작은 폰트 7~8pt + 'N)' 시작) 제외 — 부가 인용·설명이라
            # Q&A 가치 낮고 용량만 차지. 본문·별표(9pt+)는 폰트로 구분돼 보존됨.
            is_footnote = (kind == "law_comment" and 0 < buf_size[0] <= 8.5
                           and re.match(r"\d+\)", para))
            if para and not is_footnote:
                para = FIGURE_CAPTION.sub(r'\n\1 ', para).strip()
                para = split_figure_caption_lines(para)   # R14-2
                out.append(para)
            buf.clear()
        buf_size[0] = 0.0

    for page in doc:
        for y0, x0, raw, size in doc_lines(page):
            stripped = re.sub(r"\s+", " ", raw).strip()

            # ─ 헤더 판정 ─
            if kind == "law_comment":
                if ARTICLE_LINE.match(stripped):       # 제N조(제목) 헤더
                    flush()
                    out.append(stripped)
                    prev_y[0] = None
                    continue
                if size >= body + 1.2 and len(stripped) < 60:   # 소제목(1./가.)
                    flush()
                    out.append(stripped)
                    prev_y[0] = None
                    continue
            if kind == "topic_doc":
                if size >= body + 4 and len(stripped) < 60:
                    flush()
                    out.append("# " + stripped)
                    prev_y[0] = None
                    continue
                if (size >= body + 1.2 and len(stripped) < 50
                        and SUBHEAD_PAT.match(stripped)):
                    flush()
                    out.append("## " + stripped)
                    prev_y[0] = None
                    continue

            # ─ 본문 줄 — 단락 경계 판정 ─
            if buf:
                font_change = abs(size - buf_size[0]) > 1.6
                gap_break = (prev_y[0] is not None
                             and (y0 - prev_y[0]) > thr
                             and "".join(buf).rstrip().endswith(SENT_TERM))
                if font_change or gap_break:
                    flush()
            # R12-B: 번호·기호 항목은 새 단락으로 (조문 원문 목록 1.2.3./가.나./①②③)
            if buf and LIST_MARKER.match(stripped):
                flush()
            if not buf:
                buf_size[0] = size
            buf.append(raw)
            prev_y[0] = y0
        prev_y[0] = None      # 페이지 경계: 버퍼 유지(연속 단락), 간격 판정만 리셋
    flush()
    return out


def postprocess(out, kind):
    """줄나뉜 절·장 제목 병합 + 표지·발간사·목차 등 앞부분 제거."""
    # 1. '제N절'·'제N장'만 있는 헤더에 바로 뒤 헤더(제목)를 병합
    merged = []
    for entry in out:
        if entry.startswith("#") and merged and BARE_HEAD.match(merged[-1]):
            merged[-1] = merged[-1].rstrip() + " " + entry.lstrip("# ").strip()
        else:
            merged.append(entry)
    # 2. 앞부분 표지·발간사·목차 제거
    if kind == "law_comment":
        for i, e in enumerate(merged):           # 첫 '제N조(제목)' 헤더부터
            if ARTICLE_LINE.match(e):
                return merged[i:]
        return merged
    first_sub = next((i for i, e in enumerate(merged) if e.startswith("## ")), None)
    if first_sub is None:
        return merged
    start = first_sub                            # 첫 '##' 직전의 '#'(절 제목)부터
    for j in range(first_sub - 1, -1, -1):
        if merged[j].startswith("# "):
            start = j
            break
    # 앞부분 제거가 문서의 20%를 넘으면 표지가 아니라 헤더가 드문 것 → 제거 안 함
    if start > len(merged) * 0.2:
        return merged
    return merged[start:]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for src in SOURCES:
        pdf_path = PDF_DIR / src["pdf"]
        if not pdf_path.exists():
            print(f"❌ PDF 없음: {pdf_path}")
            continue
        print(f"\n📄 {src['pdf']}")
        try:
            with fitz.open(pdf_path) as doc:
                body = body_font(doc)
                lh = global_line_height(doc)
                print(f"   {doc.page_count}쪽 · 본문폰트 {body} · 줄높이 {lh}")
                paras = postprocess(extract(doc, src["kind"], body, lh),
                                    src["kind"])
        except Exception as e:                       # PDF 1개 실패가 전체를 막지 않게
            print(f"   ❌ 처리 실패: {e} — 이 PDF 건너뜀")
            continue

        if src["kind"] == "law_comment":
            arts = sum(1 for p in paras if ARTICLE_LINE.match(p))
            print(f"   단락 {len(paras)}개 · 조문헤더 {arts}개")
        else:
            heads = sum(1 for p in paras if p.startswith("#"))
            print(f"   단락 {len(paras)}개 · 헤더 {heads}개")

        text = src["head"] + "\n\n" + "\n\n".join(paras) + "\n"
        out_path = OUT_DIR / src["out"]
        out_path.write_text(text, encoding="utf-8")
        print(f"   ✅ 저장: {out_path}  ({len(text):,}자)")

    print(f"\n완료. 출력 폴더: {OUT_DIR}")
    print("검토 후 sources_config.json의 source_dir로 옮기고 build_indexes.py 재실행.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
