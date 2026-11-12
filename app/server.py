"""供应商归一核对页 —— 标准库实现的 Web 服务。

路由：
  GET  /                 核对页面（静态 HTML/JS/CSS 全部内联，可离线浏览）
  GET  /healthz          健康检查
  POST /api/crawl        {"url": "..."}  抓取并返回分组结果
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .crawler import crawl
from .normalize import build_groups

STATIC_INDEX = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>供应商归一核对页</title>
<style>
  :root { --border:#d0d5dd; --bg-soft:#f6f8fa; --warn-bg:#fff7ed;
          --warn-border:#f59e0b; --danger-bg:#fef2f2; --danger-border:#ef4444;
          --ok:#047857; --muted:#667085; }
  * { box-sizing: border-box; }
  body { margin:0; font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",
         "Noto Sans CJK SC",sans-serif; color:#1d2939; background:#f9fafb; }
  header { background:#102a43; color:#fff; padding:16px 24px; }
  header h1 { margin:0; font-size:18px; }
  header p { margin:4px 0 0; color:#bcccdc; font-size:12px; }
  main { max-width:1080px; margin:24px auto; padding:0 16px; }
  .panel { background:#fff; border:1px solid var(--border); border-radius:8px;
           padding:16px; margin-bottom:20px; }
  form { display:flex; gap:8px; }
  input[type=url] { flex:1; padding:8px 10px; border:1px solid var(--border);
                    border-radius:6px; font-size:14px; }
  button { padding:8px 18px; border:0; border-radius:6px; background:#0e7490;
           color:#fff; font-size:14px; cursor:pointer; }
  button:disabled { background:#94a3b8; cursor:wait; }
  .banner { border-radius:6px; padding:10px 14px; margin-bottom:16px; font-size:13px; }
  .banner.warn { background:var(--warn-bg); border:1px solid var(--warn-border); }
  .banner.info { background:#eff6ff; border:1px solid #93c5fd; }
  h2 { font-size:15px; margin:20px 0 10px; border-left:3px solid #0e7490;
       padding-left:8px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th,td { border:1px solid var(--border); padding:8px 10px; text-align:left;
          vertical-align:top; }
  th { background:var(--bg-soft); white-space:nowrap; }
  .group-card { border:1px solid var(--border); border-radius:8px; padding:14px;
                margin-bottom:14px; }
  .group-head { display:flex; flex-wrap:wrap; gap:10px; align-items:baseline;
                margin-bottom:8px; }
  .code { font-family:ui-monospace,Menlo,Consolas,monospace; font-weight:600;
          background:#ecfeff; padding:2px 8px; border-radius:4px; }
  .tag { display:inline-block; font-size:12px; padding:1px 8px; border-radius:999px; }
  .tag.ambiguous { background:var(--danger-bg); color:#b91c1c;
                   border:1px solid var(--danger-border); }
  .tag.unmatched { background:var(--warn-bg); color:#b45309;
                   border:1px solid var(--warn-border); }
  .muted { color:var(--muted); font-size:12px; }
  .src { font-size:12px; color:#334155; }
  .src a { color:#0e7490; text-decoration:none; word-break:break-all; }
  .names span { display:inline-block; background:var(--bg-soft); border:1px solid var(--border);
                border-radius:4px; padding:1px 8px; margin:2px 4px 2px 0; font-size:12px; }
  .error-msg { color:#b91c1c; }
  details summary { cursor:pointer; margin:6px 0; font-weight:600; }
  .fail-item { font-size:12px; color:#991b1b; margin:3px 0; word-break:break-all; }
</style>
</head>
<body>
<header>
  <h1>供应商归一核对</h1>
  <p>按统一社会信用代码分组；无代码记录仅在名称唯一命中代码组时归入，不跨组串联</p>
</header>
<main>
  <div class="panel">
    <form id="crawl-form">
      <input type="url" id="url-input" required placeholder="输入中标公告目录 URL，例如 http://example-site.local:8080/list/index.html">
      <button type="submit" id="go-btn">开始抓取核对</button>
    </form>
    <p class="muted" style="margin:8px 0 0">仅沿同站分页与详情链接抓取，静态资源与跨站链接不会被访问。</p>
  </div>

  <div id="banners"></div>
  <div id="summary"></div>
  <div id="groups"></div>
  <div id="pending"></div>
  <div id="failures"></div>
</main>

<script>
const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => (
    {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function sourceCell(rec) {
  const label = esc(rec.source_announcement || rec.page_url);
  return `<div class="src"><a href="${esc(rec.page_url)}" target="_blank" rel="noopener">${label}</a></div>`;
}

function renderGroups(groups) {
  if (!groups.length) {
    $("groups").innerHTML = `<h2>代码组</h2><p class="muted">暂无带统一社会信用代码的记录。</p>`;
    return;
  }
  let html = `<h2>代码组（${groups.length} 组）</h2>`;
  for (const g of groups) {
    html += `<div class="group-card">
      <div class="group-head">
        <span class="code">${esc(g.code)}</span>
        <span class="muted">${g.records.length} 条公告记录</span>
      </div>
      <div class="names">${g.names.map(n => `<span>${esc(n)}</span>`).join("")}</div>
      <details><summary>公告来源（${g.announcement_sources.length}）</summary>
        <table><thead><tr><th>公告</th><th>页面名称</th><th>曾用名</th><th>代码</th></tr></thead>
        <tbody>${g.records.map(r => `<tr>
          <td>${sourceCell(r)}</td>
          <td>${esc(r.current_name) || '<span class="muted">—</span>'}</td>
          <td>${r.former_names.map(esc).join("、") || '<span class="muted">—</span>'}</td>
          <td>${esc(r.code) || '<span class="muted">无代码（按名称归入）</span>'}</td>
        </tr>`).join("")}</tbody></table>
      </details></div>`;
  }
  $("groups").innerHTML = html;
}

function renderPending(pending) {
  if (!pending.length) {
    $("pending").innerHTML = `<h2>待核实记录</h2><p class="muted">无。</p>`;
    return;
  }
  const reasonText = {ambiguous: "同名指向多个代码组", unmatched: "名称无法对应任何代码组"};
  let html = `<h2>待核实记录（${pending.length} 条，未并入任何代码组）</h2>
    <div class="panel"><table><thead><tr>
      <th>核实原因</th><th>公告来源</th><th>页面名称</th><th>曾用名</th><th>候选代码组</th>
    </tr></thead><tbody>`;
  for (const p of pending) {
    const r = p.record;
    html += `<tr>
      <td><span class="tag ${p.reason}">${esc(reasonText[p.reason] || p.reason)}</span></td>
      <td>${sourceCell(r)}</td>
      <td>${esc(r.current_name) || '<span class="muted">—</span>'}</td>
      <td>${r.former_names.map(esc).join("、") || '<span class="muted">—</span>'}</td>
      <td>${p.candidate_codes.length
          ? p.candidate_codes.map(c => `<span class="code">${esc(c)}</span>`).join(" ")
          : '<span class="muted">—</span>'}</td>
    </tr>`;
  }
  html += `</tbody></table></div>`;
  $("pending").innerHTML = html;
}

function renderFailures(data) {
  const box = $("failures");
  if (!data.failures.length && !data.truncated) { box.innerHTML = ""; return; }
  let html = `<h2>抓取异常（名录不完整提示）</h2><div class="panel">`;
  if (data.truncated) {
    html += `<p class="error-msg">已达到抓取上限（目录页 ${data.limits.pages} / 详情页 ${data.limits.details}），结果被截断，名录不完整。</p>`;
  }
  for (const f of data.failures) {
    html += `<div class="fail-item">✗ [${f.kind === "detail" ? "详情页" : "目录页"}]
      <a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.url)}</a> — ${esc(f.error)}</div>`;
  }
  html += `</div>`;
  box.innerHTML = html;
}

$("crawl-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = $("url-input").value.trim();
  $("banners").innerHTML = ""; $("summary").innerHTML = "";
  $("groups").innerHTML = ""; $("pending").innerHTML = ""; $("failures").innerHTML = "";
  const btn = $("go-btn"); btn.disabled = true; btn.textContent = "抓取中…";
  try {
    const resp = await fetch("/api/crawl", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url}),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || `HTTP ${resp.status}`);

    if (data.crawl.incomplete) {
      const n = data.crawl.failures.length;
      $("banners").innerHTML = `<div class="banner warn">⚠ 本次抓取存在 ${n} 个失败页面${data.crawl.truncated ? "或已达抓取上限" : ""}，<b>名录可能不完整</b>，请结合下方异常清单核对。</div>`;
    } else {
      $("banners").innerHTML = `<div class="banner info">✓ 同站页面全部抓取成功，名录完整。</div>`;
    }
    $("summary").innerHTML = `<div class="panel">访问目录页 <b>${data.crawl.limits.visited}</b> 个，
      抽取公告 <b>${data.crawl.records.length}</b> 条，
      形成代码组 <b>${data.groups.length}</b> 个，待核实 <b>${data.pending.length}</b> 条。</div>`;
    renderGroups(data.groups);
    renderPending(data.pending);
    renderFailures(data.crawl);
  } catch (err) {
    $("banners").innerHTML = `<div class="banner warn error-msg">抓取失败：${esc(err.message)}</div>`;
  } finally {
    btn.disabled = false; btn.textContent = "开始抓取核对";
  }
});
</script>
</body>
</html>"""


class _Handler(BaseHTTPRequestHandler):
    server_version = "SupplierNormalizer/1.0"

    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            body = STATIC_INDEX.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/healthz":
            self._send_json({"status": "ok"})
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self):
        if urlsplit(self.path).path != "/api/crawl":
            self._send_json({"error": "not found"}, status=404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            url = (payload.get("url") or "").strip()
            if not url:
                raise ValueError("缺少 url 参数")
            report = crawl(url)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except Exception as exc:  # noqa: BLE001 - 任何异常都转成可读错误
            self._send_json({"error": f"抓取异常: {exc}"}, status=502)
            return

        result = build_groups(report.records)
        response = result.to_dict()
        response["crawl"] = report.to_dict()
        self._send_json(response)

    def log_message(self, fmt, *args):
        # 保留一行精简访问日志
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")


def serve(host: str = "0.0.0.0", port: int = 8000):
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"供应商归一核对页: http://{host}:{port}/")
    httpd.serve_forever()


if __name__ == "__main__":
    import os
    serve(port=int(os.environ.get("PORT", "8000")))
