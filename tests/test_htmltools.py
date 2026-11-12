import unittest

import bootstrap  # noqa: F401
from app.htmltools import parse_html, extract_links, extract_fields

TABLE_HTML = """
<html><body>
<table>
  <tr><th>项目编号</th><td>ZJ-1</td></tr>
  <tr><th>中标供应商名称</th><td>表格版式公司</td></tr>
  <tr><th>曾用名</th><td>旧名一、旧名二</td></tr>
  <tr><th>统一社会信用代码</th><td>91310115MA1K39A27L</td></tr>
</table>
<a href="/list/page_2.html">下一页</a>
<a href="https://other.example.org/x">跨站</a>
<a href="/assets/site.css">样式</a>
</body></html>
"""

P_HTML = """
<html><body>
<p>供应商名称：段落版式公司</p>
<p>统一社会信用代码：91110108MA01A7B91C</p>
</body></html>
"""

DIV_HTML = """
<html><body>
<div><b>成交供应商名称：</b>div版式公司</div>
<div><b>信用代码：</b>91440101MA5C3XD62R</div>
</body></html>
"""

DL_HTML = """
<html><body>
<dl>
  <dt>中标（成交）供应商名称</dt><dd>dl版式公司</dd>
  <dt>统一社会信用代码（组织机构代码）</dt><dd>91310116MA1J8FQ45T</dd>
</dl>
</body></html>
"""

LABELS = [
    "中标（成交）供应商名称", "中标供应商名称", "成交供应商名称",
    "供应商名称", "信用代码", "统一社会信用代码",
    "统一社会信用代码（组织机构代码）", "曾用名",
]


class TestHtmlTools(unittest.TestCase):
    def test_tolerant_parse(self):
        root = parse_html("<p>未闭合段落 <div>嵌套</div>")
        self.assertIn("未闭合段落", root.text_content())
        self.assertIn("嵌套", root.text_content())

    def test_extract_links(self):
        root = parse_html(TABLE_HTML)
        hrefs = [l["href"] for l in extract_links(root)]
        self.assertIn("/list/page_2.html", hrefs)
        self.assertIn("https://other.example.org/x", hrefs)
        self.assertEqual(len(hrefs), 3)

    def test_table_layout_fields(self):
        fields = extract_fields(TABLE_HTML, LABELS)
        self.assertEqual(fields["中标供应商名称"], "表格版式公司")
        self.assertEqual(fields["曾用名"], "旧名一、旧名二")
        self.assertEqual(fields["统一社会信用代码"], "91310115MA1K39A27L")

    def test_paragraph_layout_fields(self):
        fields = extract_fields(P_HTML, LABELS)
        self.assertEqual(fields["供应商名称"], "段落版式公司")
        self.assertEqual(fields["统一社会信用代码"], "91110108MA01A7B91C")

    def test_div_layout_fields(self):
        fields = extract_fields(DIV_HTML, LABELS)
        self.assertEqual(fields["成交供应商名称"], "div版式公司")
        self.assertEqual(fields["信用代码"], "91440101MA5C3XD62R")

    def test_dl_layout_fields(self):
        fields = extract_fields(DL_HTML, LABELS)
        self.assertEqual(fields["中标（成交）供应商名称"], "dl版式公司")
        self.assertEqual(
            fields["统一社会信用代码（组织机构代码）"], "91310116MA1J8FQ45T"
        )

    def test_no_field_in_plain_page(self):
        fields = extract_fields("<html><body><h1>普通页面</h1></body></html>",
                                LABELS)
        self.assertEqual(fields, {})


if __name__ == "__main__":
    unittest.main()
