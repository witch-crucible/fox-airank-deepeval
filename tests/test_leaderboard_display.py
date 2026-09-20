import json
import subprocess
import unittest
from pathlib import Path


INDEX_PATH = Path(__file__).resolve().parent.parent / 'model_dashboard' / 'static' / 'index.html'


class LeaderboardDisplayTests(unittest.TestCase):
    def render(self, models=None, agents=None, legion_only=False, aa_only=False):
        script = r'''
          const fs = require('node:fs');
          const vm = require('node:vm');
          const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
          const source = fs.readFileSync(process.argv[1], 'utf8').split('<script>')[1].split('</script>')[0];
          new vm.Script(source);
          class Element {
            constructor(tag, className = '', text = '') { this.tag = tag; this.className = className; this.children = []; this.text = text; this.attrs = {}; this.dataset = {}; this.classList = { add: value => { this.className += ' ' + value; } }; }
            append(...children) { this.children.push(...children); }
            setAttribute(key, value) { this.attrs[key] = value; }
            addEventListener() {}
            get childNodes() { return this.children; }
            set textContent(value) { this.text = value; this.children = []; }
            get textContent() { return this.text + this.children.map(child => typeof child === 'string' ? child : child.textContent).join(' '); }
          }
          const app = new Element('main');
          const el = (tag, css, text) => new Element(tag, css, text);
          const context = vm.createContext({
            app, el, state: { modelLeaderboard: { models: payload.models }, agentLeaderboard: { agents: payload.agents },
              leaderboardSearch: '', leaderboardPage: 1, leaderboardPageSize: 50, leaderboardLegionOnly: payload.legion_only,
              modelLeaderboardAaOnly: payload.aa_only },
            number: value => value == null ? '—' : String(value), leaderboardSyncPromise: null,
            orderedModelLeaderboardSources: () => [{key: 'artificial_analysis_model', label: 'AA', heading: 'AA', weight: .5},
              {key: 'arena_webdev', label: 'Arena', heading: 'Arena', weight: .35}, {key: 'llm_stats', label: 'LLM Stats', heading: 'LLM Stats', weight: .15}],
            weightPercent: value => value * 100 + '%', panelHeader: title => el('header', '', title),
            localButton: text => el('button', '', text), runLegionLeaderboardSync() {}, render() {},
            renderModelAliasPanel: () => el('section'), renderHistoryPanel: () => el('section'),
            leaderboardModelHref: () => '', sourceDetailHref: () => '',
            leaderboardMetricLink: text => el('a', '', text)
          });
          const start = source.indexOf('    function leaderboardSourceCell(');
          const end = source.indexOf('    function renderSettingsPage(', start);
          vm.runInContext(source.slice(start, end), context);
          const agentStart = source.indexOf('    function renderAgentLeaderboardPage(');
          const agentEnd = source.indexOf('    async function loadHistoryComparison(', agentStart);
          vm.runInContext(source.slice(agentStart, agentEnd), context);
          vm.runInContext(payload.agents === null ? 'renderModelLeaderboardPage()' : 'renderAgentLeaderboardPage()', context);
          const rows = [];
          function walk(node) {
            if (typeof node === 'string') return;
            if (node.tag === 'tr') rows.push({ classes: node.className, text: node.textContent, cells: node.children.length });
            node.children.forEach(walk);
          }
          walk(app);
          process.stdout.write(JSON.stringify({text: app.textContent, rows}));
        '''
        result = subprocess.run(['node', '-e', script, str(INDEX_PATH)],
                                input=json.dumps({'models': models or [], 'agents': agents, 'legion_only': legion_only, 'aa_only': aa_only}),
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def legion(self, core=True):
        return {'matched': True, 'is_core': core, 'entries': [{'tool': 'Codex', 'primary_purpose_types': ['Build', 'Ship'],
                                                            'core_purpose_types': ['Build'] if core else []}]}

    def test_model_rows_display_effort_legion_core_and_independent_scores(self):
        rows = [
            {'model': 'Alpha', 'model_key': 'alpha', 'reasoning_effort': 'high', 'third_party_score': 90,
             'third_party_rank': 1, 'legion': self.legion(), 'sources': {}, 'local_configurations': []},
            {'model': 'Alpha', 'model_key': 'alpha', 'reasoning_effort': 'unknown', 'third_party_score': None,
             'legion': {'matched': False}, 'sources': {}, 'local_configurations': []},
        ]
        result = self.render(models=rows)
        self.assertIn('智能度', result['rows'][0]['text'])
        self.assertEqual(result['rows'][0]['cells'], 8)
        self.assertIn('★ Vibe Coding Legion', result['rows'][1]['text'])
        self.assertIn('★ Build / Ship', result['rows'][1]['text'])
        self.assertIn('leaderboard-legion-core', result['rows'][1]['classes'])
        self.assertIn('high', result['rows'][1]['text'])
        self.assertIn('未注明', result['rows'][2]['text'])
        self.assertNotIn('leaderboard-legion', result['rows'][2]['classes'])
        filtered = self.render(models=rows, legion_only=True)
        self.assertEqual(len(filtered['rows']), 2)

    def test_artificial_analysis_only_uses_official_rank_and_detailed_fields(self):
        def aa(rank, intelligence, speed, terminal_bench, cost):
            representative = {
                'model': f'Alpha {rank}',
                'scores': {'aa_model_speed': speed, 'aa_model_terminal_bench_v4': terminal_bench},
                'source': {'rank': rank, 'variants': [{
                    'host': {'name': 'Provider'}, 'cost_usd_per_task': cost,
                    'input_price_per_m': 1, 'output_price_per_m': 2, 'speed_tokens_per_second': speed,
                }]},
            }
            return {'representative': representative, 'raw_score': intelligence, 'variants': [representative]}

        rows = [
            {'model': 'Alpha', 'model_key': 'alpha', 'reasoning_effort': 'high', 'third_party_score': 99,
             'third_party_rank': 1, 'legion': {'matched': False},
             'sources': {'artificial_analysis_model': aa(9, 77, 120, 44, .42)}, 'local_configurations': []},
            {'model': 'Beta', 'model_key': 'beta', 'reasoning_effort': 'max', 'third_party_score': 20,
             'third_party_rank': 2, 'legion': self.legion(False),
             'sources': {'artificial_analysis_model': aa(2, 88, 80, 55, .25)}, 'local_configurations': []},
            {'model': 'Arena only', 'model_key': 'arena only', 'reasoning_effort': 'unknown', 'third_party_score': None,
             'legion': {'matched': False}, 'sources': {'arena_webdev': {}}, 'local_configurations': []},
        ]
        result = self.render(models=rows, aa_only=True)
        self.assertIn('Artificial Analysis only', result['text'])
        self.assertIn('AA 官方名次', result['rows'][0]['text'])
        self.assertEqual(len(result['rows']), 3)
        self.assertIn('Beta', result['rows'][1]['text'])
        self.assertIn('#2', result['rows'][1]['text'])
        self.assertIn('88', result['rows'][1]['text'])
        self.assertIn('80 tok/s', result['rows'][1]['text'])
        self.assertIn('55', result['rows'][1]['text'])
        self.assertIn('最低 $0.25/task', result['rows'][1]['text'])
        self.assertIn('Alpha', result['rows'][2]['text'])
        self.assertNotIn('Arena only', result['text'])
        legion = self.render(models=rows, aa_only=True, legion_only=True)
        self.assertEqual(len(legion['rows']), 2)
        self.assertIn('Beta', legion['rows'][1]['text'])
        self.assertNotIn('Alpha', legion['text'])

    def test_agent_supplement_has_effort_star_and_no_fabricated_agent_score(self):
        entry = {'agent': {'tool': 'Codex', 'model': 'Alpha', 'reasoning_effort': 'medium', 'scores': {}, 'source': {}},
                 'legion': self.legion(False), 'supplemental': True, 'baseline': None, 'terminal_bench_uplift': None}
        result = self.render(agents=[entry], legion_only=True)
        self.assertEqual(result['rows'][0]['cells'], 9)
        row = result['rows'][1]
        self.assertIn('☆ Vibe Coding Legion', row['text'])
        self.assertIn('Legion 补充配置', row['text'])
        self.assertIn('medium', row['text'])
        self.assertIn('无同配置成绩', row['text'])
        self.assertIn('无同配置 TB4', row['text'])
        self.assertNotIn('leaderboard-legion-core', row['classes'])


if __name__ == '__main__':
    unittest.main()
