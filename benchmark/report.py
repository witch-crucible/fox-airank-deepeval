from __future__ import annotations

import json
from typing import Any


def render_report_html(report: dict[str, Any]) -> str:
    report_json = json.dumps(report, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI 代码代理评测对比</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f4f7fb;
      --surface: #ffffff;
      --surface-soft: #f8fafc;
      --text: #172033;
      --muted: #667085;
      --border: #dfe5ee;
      --accent: #2563eb;
      --accent-soft: #dbeafe;
      --success: #16803c;
      --danger: #c43232;
      --shadow: 0 10px 30px rgba(25, 39, 68, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ width: min(1180px, calc(100% - 32px)); margin: 32px auto 56px; }}
    header {{ display: flex; align-items: end; justify-content: space-between; gap: 16px; margin-bottom: 24px; }}
    h1, h2, h3, p {{ margin-top: 0; }}
    h1 {{ margin-bottom: 4px; font-size: clamp(24px, 4vw, 36px); line-height: 1.2; }}
    h2 {{ margin-bottom: 16px; font-size: 18px; }}
    h3 {{ margin-bottom: 12px; font-size: 15px; }}
    .muted {{ color: var(--muted); }}
    .section {{ margin-top: 28px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; }}
    .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow); padding: 18px; }}
    .tool-card {{ position: relative; overflow: hidden; }}
    .tool-card:first-child::before {{ content: ""; position: absolute; inset: 0 auto 0 0; width: 4px; background: var(--accent); }}
    .rank {{ color: var(--muted); font-size: 12px; }}
    .tool-name {{ margin: 5px 0 12px; font-size: 17px; font-weight: 650; word-break: break-word; }}
    .score {{ font-size: 34px; font-weight: 720; letter-spacing: -1px; }}
    .score small {{ color: var(--muted); font-size: 13px; font-weight: 500; letter-spacing: 0; }}
    .table-wrap {{ overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow); }}
    table {{ width: 100%; border-collapse: collapse; min-width: 680px; }}
    th, td {{ padding: 12px 14px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: middle; }}
    th {{ background: var(--surface-soft); color: var(--muted); font-size: 12px; font-weight: 650; white-space: nowrap; }}
    tr:last-child td {{ border-bottom: 0; }}
    td.number, th.number {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .bar-row {{ display: grid; grid-template-columns: minmax(90px, 150px) 1fr 48px; align-items: center; gap: 10px; margin: 10px 0; }}
    .bar-track {{ height: 9px; overflow: hidden; border-radius: 99px; background: var(--border); }}
    .bar-fill {{ height: 100%; border-radius: inherit; background: var(--accent); }}
    .bar-value {{ text-align: right; font-variant-numeric: tabular-nums; }}
    details {{ border-bottom: 1px solid var(--border); }}
    details:last-child {{ border-bottom: 0; }}
    summary {{ display: grid; grid-template-columns: minmax(180px, 1fr) repeat(var(--tool-count), minmax(70px, 110px)); gap: 12px; align-items: center; padding: 14px 18px; cursor: pointer; }}
    summary:hover {{ background: var(--surface-soft); }}
    summary::marker {{ color: var(--muted); }}
    .case-title {{ font-weight: 650; }}
    .case-category {{ display: block; color: var(--muted); font-size: 12px; font-weight: 400; }}
    .case-score {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .case-score strong {{ display: block; }}
    .detail-content {{ padding: 0 18px 16px 36px; }}
    .detail-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }}
    .detail-panel {{ padding: 14px; background: var(--surface-soft); border-radius: 10px; }}
    .check {{ display: grid; grid-template-columns: 18px minmax(90px, auto) 1fr; gap: 8px; align-items: start; margin-top: 8px; }}
    .ok {{ color: var(--success); }}
    .fail {{ color: var(--danger); }}
    .detail {{ color: var(--muted); white-space: pre-wrap; overflow-wrap: anywhere; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }}
    .empty {{ padding: 28px; text-align: center; color: var(--muted); }}
    @media (max-width: 700px) {{
      main {{ width: min(100% - 20px, 1180px); margin-top: 20px; }}
      header {{ align-items: start; flex-direction: column; }}
      summary {{ grid-template-columns: 1fr; gap: 6px; }}
      .case-score {{ display: flex; justify-content: space-between; text-align: left; }}
      .detail-content {{ padding-left: 18px; }}
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #0f1420;
        --surface: #171e2d;
        --surface-soft: #1d2638;
        --text: #eef2f8;
        --muted: #a9b4c7;
        --border: #303b50;
        --accent: #76a7ff;
        --accent-soft: #243d68;
        --success: #65d58b;
        --danger: #ff8585;
        --shadow: 0 12px 32px rgba(0, 0, 0, 0.2);
      }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>AI 代码代理评测对比</h1>
        <p class="muted">总分、分类能力与逐项检查结果</p>
      </div>
      <div id="graded-at" class="muted"></div>
    </header>
    <section aria-labelledby="overall-title">
      <h2 id="overall-title">总分排名</h2>
      <div id="overall" class="cards"></div>
    </section>
    <section class="section" aria-labelledby="category-title">
      <h2 id="category-title">分类能力</h2>
      <div id="categories" class="cards"></div>
    </section>
    <section class="section" aria-labelledby="matrix-title">
      <h2 id="matrix-title">Case 得分矩阵</h2>
      <div id="matrix" class="table-wrap"></div>
    </section>
    <section class="section" aria-labelledby="detail-title">
      <h2 id="detail-title">检查详情</h2>
      <div id="details" class="card" style="padding: 0"></div>
    </section>
  </main>
  <script id="report-data" type="application/json">{report_json}</script>
  <script>
    const report = JSON.parse(document.getElementById("report-data").textContent);
    const summary = report.summary || {{}};
    const results = Array.isArray(report.results) ? report.results : [];
    const tools = Object.keys(summary).sort((a, b) => (summary[b].overall || 0) - (summary[a].overall || 0));
    const categories = [...new Set(tools.flatMap(tool => Object.keys(summary[tool].by_category || {{}})))].sort();
    const caseIds = [...new Set(results.map(item => item.case_id))];
    const create = (tag, className, text) => {{
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    }};
    const formatScore = value => Number(value || 0).toFixed(2);
    const scoreFor = (tool, caseId) => results.find(item => item.tool === tool && item.case_id === caseId);

    const gradedAt = document.getElementById("graded-at");
    if (report.graded_at) {{
      const date = new Date(report.graded_at);
      gradedAt.textContent = `评测时间：${{Number.isNaN(date.getTime()) ? report.graded_at : date.toLocaleString("zh-CN")}}`;
    }}

    const overall = document.getElementById("overall");
    tools.forEach((tool, index) => {{
      const card = create("article", "card tool-card");
      card.append(create("div", "rank", `第 ${{index + 1}} 名`));
      card.append(create("div", "tool-name", tool));
      const score = create("div", "score", formatScore(summary[tool].overall));
      score.append(create("small", "", " / 100"));
      card.append(score);
      overall.append(card);
    }});
    if (!tools.length) overall.append(create("div", "empty", "暂无评测数据"));

    const categoryRoot = document.getElementById("categories");
    categories.forEach(category => {{
      const card = create("article", "card");
      card.append(create("h3", "", category));
      tools.forEach(tool => {{
        const value = Number(summary[tool].by_category?.[category] || 0);
        const row = create("div", "bar-row");
        row.append(create("span", "", tool));
        const track = create("div", "bar-track");
        const fill = create("div", "bar-fill");
        fill.style.width = `${{Math.max(0, Math.min(100, value))}}%`;
        track.append(fill);
        row.append(track, create("span", "bar-value", formatScore(value)));
        card.append(row);
      }});
      categoryRoot.append(card);
    }});
    if (!categories.length) categoryRoot.append(create("div", "empty", "暂无分类数据"));

    const matrixRoot = document.getElementById("matrix");
    if (caseIds.length) {{
      const table = create("table");
      const thead = create("thead");
      const headRow = create("tr");
      headRow.append(create("th", "", "Case"), create("th", "", "分类"));
      tools.forEach(tool => headRow.append(create("th", "number", tool)));
      thead.append(headRow);
      const tbody = create("tbody");
      caseIds.forEach(caseId => {{
        const first = results.find(item => item.case_id === caseId);
        const row = create("tr");
        row.append(create("td", "", caseId), create("td", "muted", first?.category || "-"));
        tools.forEach(tool => {{
          const item = scoreFor(tool, caseId);
          row.append(create("td", "number", item ? formatScore(item.score) : "-"));
        }});
        tbody.append(row);
      }});
      table.append(thead, tbody);
      matrixRoot.append(table);
    }} else {{
      matrixRoot.append(create("div", "empty", "暂无 Case 数据"));
    }}

    const detailsRoot = document.getElementById("details");
    detailsRoot.style.setProperty("--tool-count", Math.max(1, tools.length));
    caseIds.forEach(caseId => {{
      const first = results.find(item => item.case_id === caseId);
      const details = create("details");
      const summaryNode = create("summary");
      const title = create("span", "case-title", caseId);
      title.append(create("span", "case-category", first?.category || "未分类"));
      summaryNode.append(title);
      tools.forEach(tool => {{
        const item = scoreFor(tool, caseId);
        const cell = create("span", "case-score");
        cell.append(create("span", "muted", tool), create("strong", "", item ? formatScore(item.score) : "-"));
        summaryNode.append(cell);
      }});
      const content = create("div", "detail-content");
      const grid = create("div", "detail-grid");
      tools.forEach(tool => {{
        const item = scoreFor(tool, caseId);
        if (!item) return;
        const panel = create("section", "detail-panel");
        panel.append(create("h3", "", tool));
        if (item.manual_score !== undefined) panel.append(create("p", "muted", `手动测试得分：${{formatScore(item.manual_score)}} / 10`));
        const checks = [{{ name: "结果协议", passed: Boolean(item.protocol?.passed), detail: item.protocol?.detail || "" }}, ...(item.checks || [])];
        checks.forEach(check => {{
          const row = create("div", "check");
          row.append(
            create("span", check.passed ? "ok" : "fail", check.passed ? "✓" : "×"),
            create("span", "", check.name),
            create("span", "detail", check.detail || "")
          );
          panel.append(row);
        }});
        grid.append(panel);
      }});
      content.append(grid);
      details.append(summaryNode, content);
      detailsRoot.append(details);
    }});
    if (!caseIds.length) detailsRoot.append(create("div", "empty", "暂无检查详情"));
  </script>
</body>
</html>
"""
