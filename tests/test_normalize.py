import unittest

import bootstrap  # noqa: F401
from app.normalize import (
    normalize_name, normalize_code, split_former_names, Record, build_groups,
)


def rec(url, name="", former=None, code=""):
    return Record(page_url=url, current_name=name,
                  former_names=former or [], code=normalize_code(code))


class TestNormalize(unittest.TestCase):
    def test_name_normalization(self):
        self.assertEqual(normalize_name(" 上海 智通　科技 "), "上海智通科技")
        self.assertEqual(normalize_name("某某公司（上海）"), "某某公司(上海)")
        self.assertEqual(normalize_name(None), "")

    def test_code_normalization(self):
        self.assertEqual(normalize_code(" 91310115ma1k39a27l "),
                         "91310115MA1K39A27L")
        # 非法长度 / 非法字符 -> 视为无有效代码
        self.assertEqual(normalize_code("12345"), "")
        self.assertEqual(normalize_code("91310115MA1K39A27O"), "")

    def test_split_former_names(self):
        self.assertEqual(
            split_former_names("甲公司、乙公司；丙公司, 丁公司/戊公司"),
            ["甲公司", "乙公司", "丙公司", "丁公司", "戊公司"],
        )
        self.assertEqual(split_former_names(None), [])
        # “无/暂无”等占位措辞不是真实曾用名
        self.assertEqual(split_former_names("无"), [])
        self.assertEqual(split_former_names("暂无"), [])


class TestBuildGroups(unittest.TestCase):
    def test_same_code_groups_and_codeless_unique_match(self):
        records = [
            rec("u1", "新名称公司", ["旧名称公司"], "91310115MA1K39A27L"),
            rec("u2", "旧名称公司", [], "91310115MA1K39A27L"),
            rec("u3", "旧名称公司"),  # 无代码，唯一命中 -> 归入
        ]
        result = build_groups(records)
        self.assertEqual(len(result.groups), 1)
        self.assertEqual(len(result.groups[0].records), 3)
        self.assertEqual(result.pending, [])
        self.assertIn("新名称公司", result.groups[0].names)

    def test_distinct_codes_never_merged(self):
        records = [
            rec("u1", "甲公司", code="91110108MA01A7B91C"),
            rec("u2", "乙公司", code="91440101MA5C3XD62R"),
        ]
        result = build_groups(records)
        self.assertEqual([g.code for g in result.groups],
                         ["91110108MA01A7B91C", "91440101MA5C3XD62R"])

    def test_codeless_bridging_two_groups_becomes_pending(self):
        records = [
            rec("u1", "甲集团", ["甲工程公司"], "91110108MA01A7B91C"),
            rec("u2", "乙数据", ["乙信息公司"], "91440101MA5C3XD62R"),
            # 无代码记录同时命中两个组的名称 -> 待核实，且不串组
            rec("u3", "甲集团", ["乙信息公司"]),
        ]
        result = build_groups(records)
        self.assertEqual(len(result.groups), 2)
        self.assertEqual(len(result.pending), 1)
        self.assertEqual(result.pending[0].reason, "ambiguous")
        self.assertEqual(set(result.pending[0].candidate_codes),
                         {"91110108MA01A7B91C", "91440101MA5C3XD62R"})
        # 关键不变量：无代码记录没有出现在任何组里
        for group in result.groups:
            self.assertTrue(all(r.code for r in group.records))

    def test_unmatched_codeless_is_pending(self):
        records = [
            rec("u1", "甲公司", code="91110108MA01A7B91C"),
            rec("u2", "完全陌生的公司"),
        ]
        result = build_groups(records)
        self.assertEqual(len(result.groups), 1)
        self.assertEqual(len(result.pending), 1)
        self.assertEqual(result.pending[0].reason, "unmatched")

    def test_name_conflict_between_coded_records_excludes_name(self):
        records = [
            rec("u1", "同名公司", code="91310115MA1K39A27L"),
            rec("u2", "同名公司", code="91310116MA1J8FQ45T"),
            rec("u3", "同名公司"),  # 多义名称 -> 待核实
        ]
        result = build_groups(records)
        self.assertEqual(len(result.groups), 2)
        self.assertEqual(len(result.pending), 1)
        self.assertEqual(result.pending[0].reason, "ambiguous")
        self.assertEqual(set(result.pending[0].candidate_codes),
                         {"91310115MA1K39A27L", "91310116MA1J8FQ45T"})

    def test_codeless_chain_cannot_bridge(self):
        """链式传播场景：无代码记录只能读代码组建立的索引，绝不回写。"""
        records = [
            rec("u1", "甲公司", ["共用名称"], "91310115MA1K39A27L"),
            rec("u2", "乙公司", code="91310116MA1J8FQ45T"),
            # r3：现名命中 G1，曾用名“中转名称”由 u4 指向 G2 ->
            # 一条无代码记录涉及两个代码组，必须待核实，不得归入任一组
            rec("u3", "共用名称", ["中转名称"]),
            rec("u4", "中转名称", code="91310116MA1J8FQ45T"),
            # r5 只认识“中转名称”，由带代码的 u4 唯一命中 G2
            rec("u5", "中转名称"),
        ]
        result = build_groups(records)
        by_code = {g.code: g for g in result.groups}
        g1_urls = {r.page_url for r in by_code["91310115MA1K39A27L"].records}
        g2_urls = {r.page_url for r in by_code["91310116MA1J8FQ45T"].records}
        self.assertEqual(g1_urls, {"u1"})
        self.assertEqual(g2_urls, {"u2", "u4", "u5"})
        self.assertEqual(len(result.pending), 1)
        self.assertEqual(result.pending[0].record.page_url, "u3")
        self.assertEqual(result.pending[0].reason, "ambiguous")
        self.assertEqual(set(result.pending[0].candidate_codes),
                         {"91310115MA1K39A27L", "91310116MA1J8FQ45T"})

    def test_announcement_sources_exported(self):
        records = [
            Record(page_url="http://x/a.html", title="公告A",
                   source_announcement="公告A",
                   current_name="甲公司", code="91310108MA01A7B91C"),
        ]
        result = build_groups(records).to_dict()
        self.assertEqual(result["groups"][0]["announcement_sources"], ["公告A"])


if __name__ == "__main__":
    unittest.main()
