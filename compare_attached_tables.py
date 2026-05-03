"""
별표/별지 변경 감지 (워크플로 알림용)
========================================
직전 commit의 attached_tables.json과 새로 빌드된 attached_tables.json을 비교하여
별표·별지가 추가/제거/변경됐는지 감지하고, GitHub Actions outputs로 결과를 전달한다.

워크플로에서 이 스크립트의 출력이 issue body에 첨부되어, 사용자가 이메일로 받는 알림에
"이번 주 새 별표 추가됨" 같은 정보가 포함된다.

사용법:
    python compare_attached_tables.py <old_json> <new_json>
    # GitHub Actions: env GITHUB_OUTPUT=<path> python compare_attached_tables.py ...

출력 (GITHUB_OUTPUT에 기록):
    has_table_changes=true|false
    table_changes_text=<multiline 본문 — 추가/제거/변경 목록>
    table_changes_count=<숫자>

콘솔에도 동일 내용 출력 (로그용).

비교 기준:
    - 추가: 새 파일에만 있는 키 (예: 새로 신설된 별표)
    - 제거: 옛 파일에만 있는 키 (예: 폐지된 별표)
    - 변경: 양쪽에 있지만 PDF URL 또는 제목이 다른 경우
        ※ HWP·PDF_BASE64는 기술적 차이일 뿐이라 변경 감지에서 제외
        ※ "내용" 필드도 매주 미세하게 바뀔 수 있어 신호 노이즈 우려로 제외
        → 사용자 입장의 "의미 있는 변경"만 알림: 별표 추가·제거, 제목 변경, PDF 교체
"""

import json
import os
import sys


def load_safe(path):
    """파일 없거나 읽기 실패 시 빈 dict (워크플로 첫 실행 등)."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def diff(old, new):
    """두 attached_tables 비교. (추가, 제거, 변경) 반환. 각 항목은 (law_type, key, 제목)."""
    added, removed, changed = [], [], []
    for law_type in ["시행령", "시행규칙"]:
        old_law = old.get(law_type, {})
        new_law = new.get(law_type, {})
        old_keys = set(old_law.keys())
        new_keys = set(new_law.keys())

        for k in sorted(new_keys - old_keys):
            added.append((law_type, k, new_law[k].get("제목", "")))
        for k in sorted(old_keys - new_keys):
            removed.append((law_type, k, old_law[k].get("제목", "")))
        for k in sorted(old_keys & new_keys):
            o, n = old_law[k], new_law[k]
            if o.get("PDF") != n.get("PDF") or o.get("제목") != n.get("제목"):
                changed.append((law_type, k, n.get("제목", "")))
    return added, removed, changed


def format_text(added, removed, changed):
    """사람이 읽기 좋은 multiline 텍스트 (issue body 삽입용)."""
    lines = []
    if added:
        lines.append("🆕 새로 추가된 별표/별지:")
        for law, key, title in added:
            lines.append(f"  - {law} {key}: {title}")
        lines.append("")
    if removed:
        lines.append("🗑️ 제거된 별표/별지 (폐지·번호 변경):")
        for law, key, title in removed:
            lines.append(f"  - {law} {key}: {title}")
        lines.append("")
    if changed:
        lines.append("✏️ 내용 변경된 별표/별지 (제목 또는 PDF 교체):")
        for law, key, title in changed:
            lines.append(f"  - {law} {key}: {title}")
        lines.append("")
    if added or removed or changed:
        lines.append("📌 다음 단계:")
        lines.append("  Claude에게 \"별표 변경 감지됐어\"라고 알려주시면 함께 점검합니다.")
        lines.append("  (보통은 자동 갱신이 모든 정보를 정확히 반영하므로 별도 작업 불필요)")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 3:
        print("사용법: python compare_attached_tables.py <old_json> <new_json>")
        sys.exit(2)

    old_path, new_path = sys.argv[1], sys.argv[2]
    old = load_safe(old_path)
    new = load_safe(new_path)

    added, removed, changed = diff(old, new)
    total = len(added) + len(removed) + len(changed)
    has_changes = total > 0

    text = format_text(added, removed, changed)

    # 콘솔 출력 (워크플로 로그용)
    print("=" * 60)
    print("  별표/별지 변경 감지")
    print("=" * 60)
    print(f"추가: {len(added)}, 제거: {len(removed)}, 변경: {len(changed)} (총 {total})")
    if has_changes:
        print()
        print(text)
    else:
        print("변경 없음 (별표·별지 추가·제거·교체 발견되지 않음)")
    print("=" * 60)

    # GitHub Actions outputs (있을 때만)
    out_path = os.environ.get("GITHUB_OUTPUT")
    if out_path:
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(f"has_table_changes={'true' if has_changes else 'false'}\n")
            f.write(f"table_changes_count={total}\n")
            # multiline output: heredoc 형식
            f.write("table_changes_text<<EOF_TABLE_CHANGES\n")
            f.write(text)
            f.write("\nEOF_TABLE_CHANGES\n")


if __name__ == "__main__":
    main()
