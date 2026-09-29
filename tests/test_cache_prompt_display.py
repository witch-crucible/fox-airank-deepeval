"""缓存同步提示（顶部提示条 + 「更多 → 缓存状态」列表）的文案与结构回归。

沿用仓库既有的前端切片做法：从 `static/index.html` 的单个 `<script>` 中截出
缓存提示相关函数，在最小 DOM 桩上执行，再对渲染结果做断言。
"""

import json
import subprocess
import unittest
from pathlib import Path


INDEX_PATH = Path(__file__).resolve().parent.parent / "model_dashboard" / "static" / "index.html"

#: 切片边界：从缓存更新状态声明开始，到下一个业务函数为止。
SLICE_START = "    const cacheUpdateState = {"
SLICE_END = "    function filteredModels("

RENDER_SCRIPT = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const html = fs.readFileSync(process.argv[1], "utf8");
const source = html.split("<script>")[1].split("</script>")[0];
new vm.Script(source);

const start = source.indexOf(process.argv[2]);
const end = source.indexOf(process.argv[3], start);
if (start < 0 || end < 0) throw new Error("缓存提示函数缺失或已被移动");

const input = JSON.parse(fs.readFileSync(0, "utf8"));

class Node {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.className = "";
    this.textContent = "";
    this.hidden = false;
    this.disabled = false;
    this.attrs = {};
    this.listeners = {};
  }
  append(...kids) { this.children.push(...kids); }
  replaceChildren(...kids) { this.children = kids; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  setAttribute(name, value) { this.attrs[name] = value; }
  getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null; }
}

const nodes = {};
const document = {
  createElement: tag => new Node(tag),
  getElementById: id => (nodes[id] = nodes[id] || new Node("div"))
};
const el = (tag, className, text) => {
  const node = new Node(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};
const dateTime = value => (value ? "T<" + value + ">" : "未知");

const context = vm.createContext({
  state: input.state,
  document,
  el,
  dateTime,
  leaderboardSyncPromise: null,
  console
});
vm.runInContext(source.slice(start, end), context);

vm.runInContext(
  "cacheUpdateState.busy = " + (input.busy ? "true" : "false") + ";\n"
  + "cacheUpdateState.notice = " + JSON.stringify(input.notice) + ";\n"
  + input.failures.map(pair => "cacheUpdateState.failures.set(" + JSON.stringify(pair[0]) + ", " + JSON.stringify(pair[1]) + ");").join("\n") + "\n"
  + "renderCacheBanner();",
  context
);

const flat = node => (node.textContent || "") + node.children.map(flat).join("");
const describeBannerRow = row => ({
  className: row.className,
  parts: row.children.map(flat),
  button: row.children.length > 2
    ? { text: flat(row.children[2]), disabled: row.children[2].disabled }
    : null
});

const banner = nodes["cache-banner"];
const statusContainer = nodes["cache-status-list"];
const head = banner.children[0];
const list = banner.children[1];
const payload = {
  banner: {
    hidden: banner.hidden,
    childCount: banner.children.length,
    title: head ? flat(head.children[0].children[0]) : "",
    note: head ? flat(head.children[0].children[1]) : "",
    allButton: head ? { text: flat(head.children[1].children[0]), disabled: head.children[1].children[0].disabled } : null,
    rows: list ? list.children.map(describeBannerRow) : []
  },
  statusRows: statusContainer.children.map(row => ({
    parts: row.children.map(flat),
    badge: row.children.length > 2
      ? { text: flat(row.children[2]), className: row.children[2].className }
      : null,
    button: row.children.length > 3
      ? { text: flat(row.children[3]), disabled: row.children[3].disabled }
      : null
  })),
  failures: vm.runInContext("[...cacheUpdateState.failures.keys()]", context)
};
process.stdout.write(JSON.stringify(payload));
"""


def source_row(key, label, *, cached_at=None, stale=True, reason="", kind="leaderboard"):
    """构造与 data_cache.cache_status() 输出同构的来源条目。"""
    return {
        "key": key,
        "label": label,
        "kind": kind,
        "cached_at": cached_at,
        "age_hours": None,
        "max_age_hours": 24,
        "stale": stale,
        "reason": reason,
    }


def local_row(*, cached_at=None, stale=True, reason=""):
    return source_row("local_benchmarks", "本地实测", cached_at=cached_at, stale=stale,
                      reason=reason, kind="local")


class CachePromptDisplayTests(unittest.TestCase):
    maxDiff = None

    def render(self, sources, *, failures=None, notice="", busy=False, status_error=""):
        state = {
            "cacheStatus": {"checked_at": "2026-09-29T00:00:00+00:00", "sources": sources},
            "cacheStatusError": status_error,
        }
        result = subprocess.run(
            ["node", "-e", RENDER_SCRIPT, str(INDEX_PATH), SLICE_START, SLICE_END],
            input=json.dumps({
                "state": state,
                "failures": failures or [],
                "notice": notice,
                "busy": busy,
            }),
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)

    # —— 横幅文案与信息结构 ——

    def test_banner_headline_names_stale_sources_without_dangling_phrase(self):
        snapshot = self.render([
            local_row(cached_at="2026-09-28T03:00:00+00:00", reason="runs/ 有新的运行或评测结果"),
            source_row("arena_webdev", "Arena", cached_at="2026-09-20T00:00:00+00:00", reason="已超过 24 小时未同步"),
            source_row("artificial_analysis_model", "AA Model", cached_at="2026-09-29T05:00:00+00:00", stale=False),
        ])
        banner = snapshot["banner"]
        self.assertFalse(banner["hidden"])
        self.assertEqual(banner["title"], "以下数据源的缓存已过期：本地实测、Arena")
        self.assertNotIn("需要更新", banner["title"])
        self.assertEqual(banner["note"], "页面仍展示缓存数据，可逐项更新，也可一次全部更新。")
        self.assertEqual(banner["allButton"]["text"], "全部更新")
        self.assertFalse(banner["allButton"]["disabled"])
        # 只列出过期来源，且每条都带来源名，便于与头部对应。
        self.assertEqual([row["parts"][0] for row in banner["rows"]], ["本地实测", "Arena"])

    def test_banner_row_does_not_render_cache_time_for_missing_cache(self):
        snapshot = self.render([
            local_row(cached_at=None, reason="尚未建立缓存"),
            source_row("llm_stats", "LLM Stats", cached_at=None, reason="尚未同步"),
        ])
        rows = snapshot["banner"]["rows"]
        for row in rows:
            self.assertNotIn("未知", row["parts"][1])
        self.assertEqual(rows[0]["parts"][1], "尚未建立缓存")
        self.assertEqual(rows[1]["parts"][1], "尚未同步")

    def test_banner_row_keeps_cache_time_and_reason_when_both_present(self):
        snapshot = self.render([
            source_row("arena_webdev", "Arena", cached_at="2026-09-20T00:00:00+00:00", reason="已超过 24 小时未同步"),
        ])
        detail = snapshot["banner"]["rows"][0]["parts"][1]
        self.assertTrue(detail.startswith("缓存于 T<2026-09-20T00:00:00+00:00> · "), detail)
        self.assertIn("已超过 24 小时未同步", detail)

    def test_banner_is_hidden_and_empty_when_nothing_is_stale(self):
        snapshot = self.render([
            local_row(cached_at="2026-09-29T05:00:00+00:00", stale=False),
            source_row("arena_webdev", "Arena", cached_at="2026-09-29T05:00:00+00:00", stale=False),
        ])
        self.assertTrue(snapshot["banner"]["hidden"])
        self.assertEqual(snapshot["banner"]["childCount"], 0)

    def test_banner_is_announced_to_assistive_tech(self):
        # 提示条是常驻容器，role/aria-live 写在静态 HTML 上，由 JS 切换 hidden。
        html = INDEX_PATH.read_text(encoding="utf-8")
        self.assertIn(
            '<div id="cache-banner" class="cache-banner" role="status" aria-live="polite" hidden></div>',
            html,
        )

    # —— 更新进行中 ——

    def test_progress_notice_replaces_hint_and_disables_every_entry(self):
        snapshot = self.render(
            [local_row(cached_at=None, reason="尚未建立缓存"),
             source_row("arena_webdev", "Arena", cached_at=None, reason="尚未同步")],
            notice="正在更新 本地实测、Arena…",
            busy=True,
        )
        banner = snapshot["banner"]
        self.assertEqual(banner["note"], "正在更新 本地实测、Arena…")
        self.assertEqual(banner["allButton"]["text"], "正在更新…")
        self.assertTrue(banner["allButton"]["disabled"])
        self.assertTrue(all(row["button"]["disabled"] for row in banner["rows"]))

    # —— 失败与重试 ——

    def test_failed_source_keeps_reason_and_offers_retry(self):
        snapshot = self.render(
            [local_row(cached_at="2026-09-28T03:00:00+00:00", reason="runs/ 有新的运行或评测结果"),
             source_row("arena_webdev", "Arena", cached_at="2026-09-20T00:00:00+00:00", reason="已超过 24 小时未同步")],
            failures=[["arena_webdev", "上游 503"]],
        )
        arena = snapshot["banner"]["rows"][1]
        self.assertEqual(arena["className"], "failed")
        self.assertIn("上次更新失败：上游 503", arena["parts"][1])
        self.assertEqual(arena["button"]["text"], "重试")
        local = snapshot["banner"]["rows"][0]
        self.assertEqual(local["className"], "")
        self.assertEqual(local["button"]["text"], "更新")
        self.assertNotIn("上次更新失败", local["parts"][1])

    def test_failure_record_is_dropped_once_source_becomes_fresh(self):
        snapshot = self.render(
            [local_row(cached_at=None, reason="尚未建立缓存"),
             source_row("arena_webdev", "Arena", cached_at="2026-09-29T05:00:00+00:00", stale=False)],
            failures=[["arena_webdev", "上游 503"], ["local_benchmarks", "读取 runs/ 失败"]],
        )
        # arena 已不再过期，其失败记录被清理；本地实测仍过期，记录保留。
        self.assertEqual(snapshot["failures"], ["local_benchmarks"])
        self.assertEqual(len(snapshot["banner"]["rows"]), 1)

    # —— 「更多 → 缓存状态」列表 ——

    def test_status_list_marks_stale_state_and_failure(self):
        snapshot = self.render(
            [local_row(cached_at="2026-09-28T03:00:00+00:00", reason="runs/ 有新的运行或评测结果"),
             source_row("arena_webdev", "Arena", cached_at="2026-09-20T00:00:00+00:00", reason="已超过 24 小时未同步"),
             source_row("artificial_analysis_model", "AA Model", cached_at="2026-09-29T05:00:00+00:00", stale=False)],
            failures=[["arena_webdev", "上游 503"]],
        )
        rows = {row["parts"][0]: row for row in snapshot["statusRows"]}
        self.assertEqual(list(rows), ["本地实测", "Arena", "AA Model"])
        self.assertEqual(rows["本地实测"]["badge"]["text"], "待更新")
        self.assertIn("stale", rows["本地实测"]["badge"]["className"])
        self.assertEqual(rows["本地实测"]["button"]["text"], "更新")
        self.assertTrue(rows["本地实测"]["parts"][1].startswith("缓存于 "))

    def test_status_list_shows_failed_badge_and_retry(self):
        snapshot = self.render(
            [source_row("arena_webdev", "Arena", cached_at="2026-09-20T00:00:00+00:00", reason="已超过 24 小时未同步")],
            failures=[["arena_webdev", "上游 503"]],
        )
        row = snapshot["statusRows"][0]
        self.assertEqual(row["badge"]["text"], "更新失败")
        self.assertIn("failed", row["badge"]["className"])
        self.assertEqual(row["button"]["text"], "重试")

    def test_status_list_marks_fresh_source_without_action(self):
        snapshot = self.render([source_row("artificial_analysis_model", "AA Model",
                                           cached_at="2026-09-29T05:00:00+00:00", stale=False)])
        row = snapshot["statusRows"][0]
        self.assertEqual(row["badge"]["text"], "最新")
        self.assertNotIn("stale", row["badge"]["className"])
        self.assertIsNone(row["button"])

    def test_status_list_never_shows_cache_time_for_missing_cache(self):
        snapshot = self.render([source_row("llm_stats", "LLM Stats", cached_at=None, reason="尚未同步")])
        parts = snapshot["statusRows"][0]["parts"]
        self.assertEqual(parts[1], "尚未同步")
        self.assertNotIn("未知", parts[1])

    def test_status_list_reports_read_failure(self):
        snapshot = self.render([], status_error="连接被拒绝")
        self.assertEqual(len(snapshot["statusRows"]), 1)
        self.assertEqual(snapshot["statusRows"][0]["parts"], ["缓存状态读取失败：连接被拒绝"])

    # —— 源码层面的约定 ——

    def test_batch_updates_are_issued_concurrently(self):
        html = INDEX_PATH.read_text(encoding="utf-8")
        # 并发更新依赖 allSettled + 一次性派发，不再逐源串行 await。
        start = html.index("    async function runCacheUpdates(")
        end = html.index("    async function updateCacheSource(", start)
        block = html[start:end]
        self.assertIn("Promise.allSettled(sources.map(", block)
        self.assertNotIn("for (const source of sources)", block)


if __name__ == "__main__":
    unittest.main()
