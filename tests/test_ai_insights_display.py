import json
import subprocess
import unittest
from pathlib import Path


INDEX_PATH = Path(__file__).resolve().parent.parent / "model_dashboard" / "static" / "index.html"


class AiInsightsDisplayTests(unittest.TestCase):
    def render(self, payload):
        script = r'''
          const fs = require('node:fs');
          const vm = require('node:vm');
          const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
          const html = fs.readFileSync(process.argv[1], 'utf8');
          const source = html.split('<script>')[1].split('</script>')[0];
          new vm.Script(source);
          class Element {
            constructor(tag, className = '', text = '') {
              this.tag = tag; this.className = className; this.children = []; this.text = text;
              this.attrs = {}; this.listeners = {}; this.dataset = {}; this.value = '';
              this.disabled = false; this.type = ''; this.classList = { add() {}, toggle() {} };
            }
            append(...children) { this.children.push(...children); }
            replaceChildren(...children) { this.children = children; this.text = ''; }
            setAttribute(key, value) { this.attrs[key] = String(value); }
            addEventListener(name, callback) { this.listeners[name] = callback; }
            set textContent(value) { this.text = String(value); this.children = []; }
            get textContent() {
              return this.text + this.children.map(child => typeof child === 'string' ? child : child.textContent).join('');
            }
          }
          const el = (tag, className = '', text = '') => new Element(tag, className, text);
          const app = new Element('main');
          const document = { createElement: tag => new Element(tag) };
          const dateTime = value => (value ? String(value) : '未知');
          const state = Object.assign({
            aiInsights: null, aiInsightsError: '', aiInsightsLoaded: false, aiInsightsLoading: false,
            aiInsightsGenerating: false, aiInsightsGoal: '', aiInsightsPromise: null,
            aiInsightsReadVersion: 0, aiInsightsOpen: false, view: 'recommendations'
          }, payload.state || {});
          const calls = [];
          const api = async (path, options) => {
            calls.push({ path, options: options || null });
            if (payload.apiError) throw new Error(payload.apiError);
            return payload.apiResponse;
          };
          const context = vm.createContext({ app, document, state, api, el, dateTime, render() {}, JSON });
          const start = source.indexOf('    function aiInsightText(');
          const end = source.indexOf('    function agentConfigurationRank(', start);
          if (start < 0 || end < 0) throw new Error('AI insights functions were not found');
          vm.runInContext(source.slice(start, end), context);
          function walk(node, result = []) {
            if (!node || typeof node === 'string') return result;
            result.push(node);
            node.children.forEach(child => walk(child, result));
            return result;
          }
          function serialize(node) {
            if (typeof node === 'string') return node;
            return { tag: node.tag, className: node.className, text: node.text, value: node.value,
              disabled: node.disabled, attrs: node.attrs, children: node.children.map(serialize) };
          }
          (async () => {
            vm.runInContext('app.replaceChildren(renderAiInsightsPanel())', context);
            if (payload.operation === 'refresh') await vm.runInContext('refreshAiInsights()', context);
            if (payload.operation === 'generate') await vm.runInContext(`runAiInsights(${JSON.stringify(payload.goal || '')})`, context);
            if (payload.operation === 'submit') {
              const nodes = walk(app);
              const goal = nodes.find(node => node.tag === 'textarea');
              goal.value = payload.goal || '';
              const form = nodes.find(node => node.tag === 'form');
              await form.listeners.submit({ preventDefault() {} });
            }
            vm.runInContext('app.replaceChildren(renderAiInsightsPanel())', context);
            const result = {
              tree: serialize(app), text: app.textContent, calls,
              tags: walk(app).map(node => node.tag),
              state: {
                analysis: state.aiInsights?.analysis || null,
                error: state.aiInsightsError,
                loaded: state.aiInsightsLoaded,
                loading: state.aiInsightsLoading,
                generating: state.aiInsightsGenerating,
                goal: state.aiInsightsGoal,
                open: state.aiInsightsOpen
              }
            };
            process.stdout.write(JSON.stringify(result));
          })().catch(error => { process.stderr.write(String(error.stack || error)); process.exitCode = 1; });
        '''
        result = subprocess.run(
            ["node", "-e", script, str(INDEX_PATH)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    def sensenova_config(self, available=True, timeout=180):
        return {
            "provider": "sensenova", "base_url": "https://token.sensenova.cn/v1",
            "model": "sensenova-6.8-flash-lite", "timeout_seconds": timeout, "available": available,
        }

    def test_renders_provenance_and_keeps_model_output_as_text(self):
        result = self.render({
            "state": {
                "aiInsightsLoaded": True,
                "aiInsights": {
                    "config": self.sensenova_config(timeout=300),
                    "analysis": {
                        "generated_at": "2026-09-26T12:00:00Z", "provider": "sensenova",
                        "model": "sensenova-6.8-flash-lite",
                        "goal": "复杂重构", "snapshot_hash": "snap-1", "summary": "<img src=x onerror=alert(1)> 总结",
                        "findings": [{"title": "<b>高分</b>", "detail": "保持 HTML 原样显示", "evidence": [{
                            "id": "E-42", "label": "ModelTest 总分", "value": 91.5, "unit": "分", "source": "ModelTest",
                            "as_of": "2026-09-25", "model": "模型-A", "tool": "Lab", "reasoning_effort": "high"
                        }]}],
                        "recommendations": [{"use_case": "<script>审查</script>", "reason": "有本地实测依据", "tradeoffs": "尚无速度分", "candidate": {
                            "id": "candidate-a", "kind": "model", "model": "模型-A", "tool": "Lab", "reasoning_effort": "high"
                        }, "evidence": [{"id": "E-42", "label": "ModelTest 总分", "value": 91.5, "unit": "分", "source": "ModelTest",
                            "as_of": "2026-09-25", "model": "模型-A", "tool": "Lab", "reasoning_effort": "high"}]}],
                        "limitations": ["<svg onload=alert(2)>"]
                    },
                    "stale": False, "busy": False, "coverage": {"candidate_count": 3, "evidence_count": 8}, "warnings": []
                }
            }
        })

        self.assertIn("<img src=x onerror=alert(1)> 总结", result["text"])
        self.assertIn("<b>高分</b>", result["text"])
        self.assertIn("<script>审查</script>", result["text"])
        self.assertIn("ModelTest", result["text"])
        self.assertIn("E-42", result["text"])
        self.assertIn("2026-09-25", result["text"])
        self.assertIn("模型-A", result["text"])
        self.assertIn("Lab", result["text"])
        self.assertIn("高", result["text"])
        self.assertNotIn("img", result["tags"])
        self.assertNotIn("script", result["tags"])
        self.assertNotIn("svg", result["tags"])
        self.assertEqual(result["calls"], [])
        self.assertEqual(result["tree"]["children"][0]["tag"], "details")
        self.assertIn("ai-insights-panel", result["tree"]["children"][0]["className"])

    def test_empty_loading_stale_and_unavailable_states_are_explained(self):
        empty = self.render({
            "state": {"aiInsightsLoaded": True, "aiInsights": {
                "config": self.sensenova_config(available=False, timeout=90),
                "analysis": None, "stale": False, "busy": False,
                "coverage": {"candidate_count": 0, "evidence_count": 0}, "warnings": []
            }}
        })
        self.assertIn("还没有 AI 分析结果", empty["text"])
        self.assertIn("服务器未配置 SENSENOVA_API_KEY", empty["text"])
        self.assertIn("未配置 Key", empty["text"])
        self.assertEqual(empty["calls"], [])

        loading = self.render({
            "state": {"aiInsightsLoaded": False, "aiInsightsLoading": True, "aiInsights": None}
        })
        self.assertIn("正在读取服务器保存的分析结果", loading["text"])
        self.assertIn("正在读取已保存的 AI 总结", loading["text"])

        stale = self.render({
            "state": {"aiInsightsLoaded": True, "aiInsights": {
                "config": self.sensenova_config(timeout=90),
                "analysis": {"generated_at": "now", "model": "sensenova-6.8-flash-lite", "goal": "x", "summary": "旧结果",
                    "findings": [], "recommendations": [], "limitations": []},
                "stale": True, "busy": False, "coverage": {"candidate_count": 1, "evidence_count": 2}, "warnings": []
            }}
        })
        self.assertIn("数据快照已过期", stale["text"])
        self.assertIn("旧结果", stale["text"])
        self.assertIn("已过期", stale["text"])

    def test_get_failure_keeps_the_previous_saved_analysis(self):
        old = {"summary": "上一次保存的总结", "findings": [], "recommendations": [], "limitations": []}
        result = self.render({
            "operation": "refresh", "apiError": "GET unavailable",
            "state": {"aiInsightsLoaded": True, "aiInsights": {
                "config": self.sensenova_config(timeout=120),
                "analysis": old, "stale": True, "busy": False,
                "coverage": {"candidate_count": 2, "evidence_count": 4}, "warnings": []
            }}
        })
        self.assertEqual(result["state"]["analysis"], old)
        self.assertIn("GET unavailable", result["text"])
        self.assertIn("上一次保存的总结", result["text"])
        self.assertIn("已有结果会继续保留", result["text"])
        self.assertEqual(result["calls"][0]["path"], "/api/ai-insights")
        self.assertIsNone(result["calls"][0]["options"])

    def test_manual_generation_sends_the_goal_and_keeps_old_result_on_failure(self):
        old = {"summary": "旧分析仍在", "findings": [], "recommendations": [], "limitations": []}
        goal = "  复杂代码审查与重构  "
        result = self.render({
            "operation": "submit", "goal": goal, "apiError": "SenseNova 超时",
            "state": {"aiInsightsLoaded": True, "aiInsights": {
                "config": self.sensenova_config(timeout=300),
                "analysis": old, "stale": False, "busy": False,
                "coverage": {"candidate_count": 4, "evidence_count": 6}, "warnings": []
            }}
        })
        self.assertEqual(result["calls"], [{"path": "/api/ai-insights", "options": {
            "method": "POST", "body": json.dumps({"goal": goal.strip()}, ensure_ascii=False, separators=(",", ":"))
        }}])
        self.assertEqual(result["state"]["analysis"], old)
        self.assertEqual(result["state"]["goal"], goal)
        self.assertIn("SenseNova 超时", result["text"])
        self.assertIn("旧分析仍在", result["text"])
        self.assertIn("已有结果会继续保留", result["text"])

    def test_missing_key_blocks_generation(self):
        result = self.render({
            "operation": "generate", "goal": "代码审查",
            "state": {"aiInsightsLoaded": True, "aiInsights": {
                "config": self.sensenova_config(available=False),
                "analysis": None, "stale": False, "busy": False,
                "coverage": {"candidate_count": 1, "evidence_count": 1}, "warnings": []
            }}
        })
        self.assertEqual(result["calls"], [])
        self.assertIn("未配置 SenseNova API Key", result["text"])

    def test_nav_tab_is_replaced_by_the_legion_panel(self):
        html = INDEX_PATH.read_text(encoding="utf-8")
        self.assertNotIn('data-view="ai-insights"', html)
        self.assertIn('"ai-insights": "recommendations"', html)
        self.assertIn('renderAiInsightsPanel()', html)
        self.assertIn('ai-insights-panel', html)
        self.assertIn('goal.maxLength = 1000', html)
        self.assertIn('setAttribute("maxlength", "1000")', html)


if __name__ == "__main__":
    unittest.main()
