"""端到端：用 http.server 挂载 example-site/html，执行完整抓取 + 分组。"""
import functools
import http.server
import threading
import unittest
from pathlib import Path

import bootstrap  # noqa: F401
from app.crawler import crawl
from app.normalize import build_groups

SITE_ROOT = Path(__file__).resolve().parent.parent / "example-site" / "html"


class CrawlerE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(
            http.server.SimpleHTTPRequestHandler, directory=str(SITE_ROOT)
        )
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever,
                                      daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def test_crawl_example_site_and_group(self):
        report = crawl(f"{self.base}/list/index.html", timeout=5)

        # 三个目录页 + about 介绍页（无字段的同站页面也会被遍历）+ 13 个详情页
        self.assertEqual(len(report.visited_pages), 17)
        self.assertEqual(len(report.records), 13)

        # 坏链登记为详情页失败 -> 名录不完整
        self.assertEqual(len(report.failures), 1)
        failure = report.failures[0]
        self.assertEqual(failure.kind, "detail")
        self.assertIn("missing-ann06", failure.url)
        self.assertTrue(report.incomplete)

        result = build_groups(report.records)
        by_code = {g.code: g for g in result.groups}

        # 4 个代码组
        self.assertEqual(
            sorted(by_code),
            [
                "91110108MA01A7B91C",
                "91310115MA1K39A27L",
                "91310116MA1J8FQ45T",
                "91440101MA5C3XD62R",
            ],
        )
        self.assertEqual(len(result.groups), 4)

        # G1：华东智通（含曾用名公告 2 条 + 无代码唯一命中 1 条）
        g1 = by_code["91310115MA1K39A27L"]
        self.assertEqual(len(g1.records), 3)
        g1_urls = {r.page_url for r in g1.records}
        self.assertIn(f"{self.base}/detail/ann10.html", g1_urls)
        self.assertIn("华东智通科技股份有限公司", g1.names)
        self.assertIn("上海智通信息技术有限公司", g1.names)
        # 组内保留公告来源
        self.assertTrue(
            any("市级智慧交通平台项目中标公告" in src
                for src in g1.to_dict()["announcement_sources"])
        )

        # G2 北辰 3 条，G3 云衡 3 条，G4 家具公司 1 条
        self.assertEqual(len(by_code["91110108MA01A7B91C"].records), 3)
        self.assertEqual(len(by_code["91440101MA5C3XD62R"].records), 3)
        self.assertEqual(len(by_code["91310116MA1J8FQ45T"].records), 1)

        # 待核实 3 条：ambiguous(ann12 跨组名称)、unmatched(ann13)、
        # ambiguous(ann14 多义名称)
        self.assertEqual(len(result.pending), 3)
        pending_by_url = {
            p.record.page_url.replace(self.base, ""): p for p in result.pending
        }
        self.assertEqual(pending_by_url["/detail/ann12.html"].reason,
                         "ambiguous")
        self.assertEqual(
            set(pending_by_url["/detail/ann12.html"].candidate_codes),
            {"91110108MA01A7B91C", "91440101MA5C3XD62R"},
        )
        self.assertEqual(pending_by_url["/detail/ann13.html"].reason,
                         "unmatched")
        self.assertEqual(pending_by_url["/detail/ann14.html"].reason,
                         "ambiguous")
        self.assertEqual(
            set(pending_by_url["/detail/ann14.html"].candidate_codes),
            {"91310115MA1K39A27L", "91310116MA1J8FQ45T"},
        )

        # 不变量：待核实的无代码记录（ann12/13/14）绝不出现在任何代码组中；
        # 组内允许出现无代码记录，但仅限名称唯一命中的 ann10
        grouped_urls = {
            r.page_url.replace(self.base, "")
            for group in result.groups for r in group.records
        }
        for pending in result.pending:
            self.assertNotIn(
                pending.record.page_url.replace(self.base, ""), grouped_urls
            )
        codeless_in_groups = [
            r.page_url.replace(self.base, "")
            for group in result.groups for r in group.records if not r.code
        ]
        self.assertEqual(codeless_in_groups, ["/detail/ann10.html"])

    def test_invalid_url_rejected(self):
        with self.assertRaises(ValueError):
            crawl("ftp://127.0.0.1/x")

    def test_truncation_flag(self):
        report = crawl(f"{self.base}/list/index.html", timeout=5,
                       max_pages=2, max_details=200)
        self.assertTrue(report.truncated)
        self.assertTrue(report.incomplete)


if __name__ == "__main__":
    unittest.main()
