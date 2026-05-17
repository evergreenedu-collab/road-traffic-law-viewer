"""parse_addenda_effective 단위 테스트."""
import unittest
from parse_addenda_effective import parse_addenda


def _bk(text: str, pub: str = "20251230", no: str = "1") -> dict:
    return {"부칙공포일자": pub, "부칙공포번호": no, "부칙내용": text}


class TestParseAddenda(unittest.TestCase):
    def test_empty_addenda(self):
        r = parse_addenda([], "20251230")
        self.assertEqual(r["main_effective_date"], "")
        self.assertEqual(r["exceptions"], [])
        self.assertEqual(r["raw_text"], "")

    def test_promulgate_day(self):
        r = parse_addenda(
            [_bk("이 법은 공포한 날부터 시행한다.")], "20251230"
        )
        self.assertEqual(r["main_effective_date"], "20251230")
        self.assertEqual(r["exceptions"], [])

    def test_explicit_date(self):
        r = parse_addenda(
            [_bk("이 법은 2026년 1월 1일부터 시행한다.")], "20251230"
        )
        self.assertEqual(r["main_effective_date"], "20260101")
        self.assertEqual(r["exceptions"], [])

    def test_relative_6_months(self):
        r = parse_addenda(
            [_bk("이 법은 공포 후 6개월이 경과한 날부터 시행한다.")],
            "20251230",
        )
        self.assertEqual(r["main_effective_date"], "20260630")

    def test_relative_1_year(self):
        r = parse_addenda(
            [_bk("이 법은 공포 후 1년이 경과한 날부터 시행한다.")],
            "20251230",
        )
        self.assertEqual(r["main_effective_date"], "20261230")

    def test_single_exception(self):
        r = parse_addenda([_bk(
            "제1조(시행일) 이 법은 공포한 날부터 시행한다. "
            "다만, 제44조의 개정규정은 공포 후 6개월이 경과한 날부터 시행한다."
        )], "20251230")
        self.assertEqual(r["main_effective_date"], "20251230")
        self.assertEqual(len(r["exceptions"]), 1)
        self.assertEqual(r["exceptions"][0]["articles"], ["44"])
        self.assertEqual(r["exceptions"][0]["effective_date"], "20260630")

    def test_article_range(self):
        r = parse_addenda([_bk(
            "이 법은 공포한 날부터 시행한다. "
            "다만, 제44조부터 제47조까지의 개정규정은 공포 후 3개월이 "
            "경과한 날부터 시행한다."
        )], "20251230")
        self.assertEqual(len(r["exceptions"]), 1)
        self.assertEqual(
            r["exceptions"][0]["articles"], ["44", "45", "46", "47"]
        )
        self.assertEqual(r["exceptions"][0]["effective_date"], "20260330")

    def test_article_branch(self):
        r = parse_addenda([_bk(
            "이 법은 공포한 날부터 시행한다. "
            "다만, 제44조의2의 개정규정은 2027년 7월 1일부터 시행한다."
        )], "20251230")
        self.assertEqual(len(r["exceptions"]), 1)
        self.assertEqual(r["exceptions"][0]["articles"], ["44의2"])
        self.assertEqual(r["exceptions"][0]["effective_date"], "20270701")

    def test_table_exception(self):
        r = parse_addenda([_bk(
            "이 영은 공포한 날부터 시행한다. "
            "다만, 별표 18의 개정규정은 공포 후 6개월이 경과한 날부터 "
            "시행한다."
        )], "20251230")
        self.assertEqual(len(r["exceptions"]), 1)
        self.assertEqual(r["exceptions"][0]["tables"], ["18"])
        self.assertEqual(r["exceptions"][0]["effective_date"], "20260630")

    def test_multiple_exceptions(self):
        r = parse_addenda([_bk(
            "이 법은 공포한 날부터 시행한다. "
            "다만, 제10조의 개정규정은 공포 후 3개월이 경과한 날부터 시행하고, "
            "다만, 제20조의 개정규정은 공포 후 6개월이 경과한 날부터 시행한다."
        )], "20251230")
        # 단서가 2개 추출되어야 함
        self.assertGreaterEqual(len(r["exceptions"]), 2)
        all_articles = [a for ex in r["exceptions"] for a in ex["articles"]]
        self.assertIn("10", all_articles)
        self.assertIn("20", all_articles)

    def test_raw_text_always_preserved(self):
        """파싱 결과와 무관하게 raw_text 는 항상 유지되어야 함."""
        weird = "이상한 부칙 텍스트인데 시행한다 단어만 있음."
        r = parse_addenda([_bk(weird)], "20251230")
        self.assertEqual(r["raw_text"], weird)

    def test_raw_text_truncation(self):
        long = "이 법은 공포한 날부터 시행한다. " + ("가" * 2000)
        r = parse_addenda([_bk(long)], "20251230")
        self.assertLessEqual(len(r["raw_text"]), 1500)
        self.assertTrue(r["raw_text"].endswith("…"))

    def test_second_article_section_ignored(self):
        """제2조(경과조치) 영역은 시행일 추론에서 제외되어야 함."""
        r = parse_addenda([_bk(
            "제1조(시행일) 이 법은 공포한 날부터 시행한다. "
            "제2조(경과조치) 이 법 시행 당시 제100조에 따라 면허를 받은 자는 …"
        )], "20251230")
        self.assertEqual(r["main_effective_date"], "20251230")
        # 제100조가 exceptions 에 들어가면 안 됨 (경과조치라서 부칙 시행일 아님)
        all_articles = [a for ex in r["exceptions"] for a in ex["articles"]]
        self.assertNotIn("100", all_articles)

    def test_single_article_item(self):
        """호 단위 부칙: '제160조제4항제4호'는 조키 + 항·호 상세로 추출."""
        r = parse_addenda([_bk(
            "제1조(시행일) 이 법은 공포한 날부터 시행한다. "
            "다만, 제160조제4항제4호의 개정규정은 공포 후 3개월이 "
            "경과한 날부터 시행한다."
        )], "20251230")
        self.assertEqual(len(r["exceptions"]), 1)
        ex = r["exceptions"][0]
        self.assertEqual(ex["articles"], ["160"])
        self.assertEqual(ex["article_items"], {"160": ["제4항제4호"]})
        self.assertEqual(ex["effective_date"], "20260330")

    def test_mixed_article_and_item(self):
        """조 전체 인용과 호 단위 인용이 섞인 경우 — bare 조는 상세에서 제외."""
        r = parse_addenda([_bk(
            "제1조(시행일) 이 법은 공포 후 6개월이 경과한 날부터 시행한다. "
            "다만, 제2조제26호 및 제96조의 개정규정은 공포한 날부터 시행한다."
        )], "20251230")
        self.assertEqual(len(r["exceptions"]), 1)
        ex = r["exceptions"][0]
        self.assertEqual(ex["articles"], ["2", "96"])
        self.assertEqual(ex["article_items"], {"2": ["제26호"]})
        self.assertEqual(ex["effective_date"], "20251230")


if __name__ == "__main__":
    unittest.main(verbosity=2)
