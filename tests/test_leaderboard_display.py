import json
import subprocess
import unittest
from pathlib import Path


INDEX_PATH = Path(__file__).resolve().parent.parent / 'model_dashboard' / 'static' / 'index.html'


class LeaderboardDisplayTests(unittest.TestCase):
    def render(self, models=None, agents=None, agent_groups=None, legion_only=False, aa_only=False, agent_sort="score"):
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
          const links = [];
          const context = vm.createContext({
            app, el, state: { modelLeaderboard: { models: payload.models }, agentLeaderboard: { agents: payload.agents, agent_groups: payload.agent_groups },
              leaderboardSearch: '', leaderboardPage: 1, leaderboardPageSize: 50, leaderboardLegionOnly: payload.legion_only,
              modelLeaderboardAaOnly: payload.aa_only, agentLeaderboardSort: payload.agent_sort },
            number: value => value == null ? '—' : String(value), leaderboardSyncPromise: null,
            orderedModelLeaderboardSources: () => [{key: 'artificial_analysis_model', label: 'AA', heading: 'AA', weight: .5},
              {key: 'arena_webdev', label: 'Arena', heading: 'Arena', weight: .35}, {key: 'llm_stats', label: 'LLM Stats', heading: 'LLM Stats', weight: .15}],
            weightPercent: value => value * 100 + '%', panelHeader: title => el('header', '', title),
            localButton: text => el('button', '', text), runLegionLeaderboardSync() {}, render() {},
            renderModelAliasPanel: () => el('section'), renderHistoryPanel: () => el('section'),
            leaderboardModelHref: () => '',
            sourceDetailHref: model => {
              const type = (model && model.source && model.source.type) || '';
              if (type === 'artificial_analysis_agent') return 'https://artificialanalysis.ai/agents/' + encodeURIComponent(model.tool || 'agent') + '#artificial-analysis-coding-agent-index';
              if (type === 'artificial_analysis_model') return 'https://artificialanalysis.ai/models/' + encodeURIComponent(model.model || 'model');
              return '';
            },
            leaderboardMetricLink: (value, href, title) => {
              const node = el('a', href ? 'leaderboard-metric-link' : '', value);
              node.href = href || ''; node.title = title || '';
              links.push({ text: value, href: node.href, title: node.title });
              return node;
            }
          });
          const start = source.indexOf('    function leaderboardSourceCell(');
          const end = source.indexOf('    function renderSettingsPage(', start);
          vm.runInContext(source.slice(start, end), context);
          const agentStart = source.indexOf('    function agentConfigurationRank(');
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
          process.stdout.write(JSON.stringify({text: app.textContent, rows, links}));
        '''
        result = subprocess.run(['node', '-e', script, str(INDEX_PATH)],
                                input=json.dumps({'models': models or [], 'agents': agents, 'agent_groups': agent_groups,
                                                  'legion_only': legion_only, 'aa_only': aa_only, 'agent_sort': agent_sort}),
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
        self.assertIn('★ Build', result['rows'][1]['text'])
        self.assertIn('Ship', result['rows'][1]['text'])
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
        self.assertEqual(result['rows'][0]['cells'], 1)
        row = result['rows'][2]
        self.assertIn('☆ Vibe Coding Legion', row['text'])
        self.assertIn('Legion 补充配置', row['text'])
        self.assertIn('medium', row['text'])
        self.assertIn('无同配置成绩', row['text'])
        self.assertIn('无同配置 TB4', row['text'])
        self.assertNotIn('leaderboard-legion-core', row['classes'])

    def test_agent_groups_sort_by_score_or_uplift_and_keep_configuration_details(self):
        def configuration(tool, model, score, uplift, rank, baseline_score=None):
            return {
                'agent': {'tool': tool, 'model': model,
                          'scores': {'artificial_analysis_index': score,
                                     'aa_terminal_bench_v4': None if baseline_score is None else baseline_score + uplift},
                          'source': {'type': 'artificial_analysis_agent', 'rank': rank}},
                'reasoning_effort': 'high', 'terminal_bench_uplift': uplift,
                'legion': {'matched': False, 'is_core': False, 'entries': []},
                'supplemental': False,
                'baseline': None if baseline_score is None else {
                    'model': model, 'scores': {'aa_model_terminal_bench_v4': baseline_score},
                    'source': {'type': 'artificial_analysis_model'}},
            }

        alpha = configuration('Alpha Agent', 'Alpha Model', 91, 2, 2, 30)
        beta = configuration('Beta Agent', 'Beta Model', 82, 18, 1, 42)
        groups = [
            {'agent': 'Beta Agent', 'configurations': [beta], 'legion': {'matched': False}},
            {'agent': 'Alpha Agent', 'configurations': [alpha], 'legion': {'matched': False}},
        ]
        score = self.render(agents=[], agent_groups=groups)
        score_groups = [row for row in score['rows'] if 'agent-leaderboard-group' in row['classes']]
        self.assertIn('Alpha Agent', score_groups[0]['text'])
        self.assertIn('Coding Agent Index 91', score_groups[0]['text'])
        self.assertIn('提升 +2 个百分点', score_groups[0]['text'])
        self.assertIn('提升前 TB4 30', score_groups[0]['text'])
        self.assertIn('提升后 TB4 32', score_groups[0]['text'])
        self.assertIn('Alpha Model', score_groups[0]['text'])
        uplift = self.render(agents=[], agent_groups=groups, agent_sort='uplift')
        uplift_groups = [row for row in uplift['rows'] if 'agent-leaderboard-group' in row['classes']]
        self.assertIn('Beta Agent', uplift_groups[0]['text'])
        self.assertIn('提升 +18 个百分点', uplift_groups[0]['text'])
        self.assertIn('提升前 TB4 42', uplift_groups[0]['text'])
        self.assertIn('提升后 TB4 60', uplift_groups[0]['text'])
        self.assertIn('Coding Agent Index 82', uplift_groups[0]['text'])
        index_links = [link for link in uplift['links'] if 'Coding Agent Index' in link['title']]
        self.assertTrue(index_links, '摘要行缺少 Coding Agent Index 跳转链接')
        self.assertEqual('82', index_links[0]['text'])
        self.assertIn('#artificial-analysis-coding-agent-index', index_links[0]['href'])
        baseline_links = [link for link in uplift['links'] if '提升前' in link['title']]
        self.assertTrue(baseline_links, '摘要行缺少提升前原始分的跳转链接')
        self.assertEqual('TB4 42', baseline_links[0]['text'])
        self.assertIn('/models/', baseline_links[0]['href'])

    def test_agent_group_summary_tags_each_metric_with_its_own_configuration(self):
        # The best index and the best uplift can live on different model/effort
        # rows, so the summary must attribute each number instead of implying
        # that the uplift turns the shown baseline into the shown index.
        def entry(model, index, uplift, baseline_score, rank):
            return {
                'agent': {'tool': 'Mixed Agent', 'model': model,
                          'scores': {'artificial_analysis_index': index,
                                     'aa_terminal_bench_v4': None if baseline_score is None else baseline_score + uplift},
                          'source': {'type': 'artificial_analysis_agent', 'rank': rank}},
                'reasoning_effort': 'high', 'terminal_bench_uplift': uplift,
                'legion': {'matched': False, 'is_core': False, 'entries': []},
                'supplemental': False,
                'baseline': None if baseline_score is None else {
                    'model': model, 'scores': {'aa_model_terminal_bench_v4': baseline_score},
                    'source': {'type': 'artificial_analysis_model'}},
            }

        index_only = entry('Index Model', 91, None, None, 1)
        uplift_only = entry('Uplift Model', 60, 18, 42, 2)
        groups = [{'agent': 'Mixed Agent', 'configurations': [uplift_only, index_only], 'legion': {'matched': False}}]
        result = self.render(agents=[], agent_groups=groups)
        row = next(row for row in result['rows'] if 'agent-leaderboard-group' in row['classes'])
        self.assertIn('Coding Agent Index 91', row['text'])
        self.assertIn('Index Model', row['text'])
        self.assertIn('提升前 TB4 42', row['text'])
        self.assertIn('提升后 TB4 60', row['text'])
        self.assertIn('提升 +18 个百分点', row['text'])
        self.assertIn('Uplift Model', row['text'])
        baseline_links = [link for link in result['links'] if '提升前' in link['title']]
        self.assertEqual('TB4 42', baseline_links[0]['text'])
        self.assertIn('/models/Uplift%20Model', baseline_links[0]['href'])

    def test_agent_group_summary_keeps_uplift_without_pre_uplift_score(self):
        entry = {
            'agent': {'tool': 'Solo Agent', 'model': 'Solo Model', 'scores': {'artificial_analysis_index': 55},
                      'source': {'type': 'artificial_analysis_agent', 'rank': 3}},
            'reasoning_effort': 'high', 'terminal_bench_uplift': 7, 'supplemental': False, 'baseline': None,
            'legion': {'matched': False, 'is_core': False, 'entries': []},
        }
        groups = [{'agent': 'Solo Agent', 'configurations': [entry], 'legion': {'matched': False}}]
        result = self.render(agents=[], agent_groups=groups, agent_sort='uplift')
        row = next(row for row in result['rows'] if 'agent-leaderboard-group' in row['classes'])
        self.assertIn('Coding Agent Index 55', row['text'])
        self.assertIn('提升 +7 个百分点', row['text'])
        self.assertNotIn('提升前', row['text'])
        self.assertEqual([], [link for link in result['links'] if '提升前' in link['title']])

    def test_agent_legion_filter_keeps_only_matched_configurations_and_group_tags(self):
        matched = {
            'agent': {'tool': 'Codex', 'model': 'Legion Model', 'scores': {'artificial_analysis_index': 70}, 'source': {'rank': 2}},
            'reasoning_effort': 'high', 'terminal_bench_uplift': 5, 'supplemental': False, 'baseline': None,
            'legion': {'matched': True, 'is_core': True, 'entries': [{
                'tool': 'Codex', 'primary_purpose_types': ['Build'], 'secondary_purpose_types': ['Review'],
                'core_purpose_types': ['Build'],
            }]},
        }
        other = {
            'agent': {'tool': 'Codex', 'model': 'Other Model', 'scores': {'artificial_analysis_index': 99}, 'source': {'rank': 1}},
            'reasoning_effort': 'max', 'terminal_bench_uplift': 30, 'supplemental': False, 'baseline': None,
            'legion': {'matched': False, 'is_core': False, 'entries': []},
        }
        groups = [{'agent': 'Codex', 'configurations': [other, matched], 'legion': {
            'matched': True, 'is_core': True, 'entries': matched['legion']['entries'],
            'primary_purpose_types': ['Build'], 'secondary_purpose_types': ['Review'], 'core_purpose_types': ['Build'],
        }}]
        result = self.render(agents=[], agent_groups=groups, legion_only=True)
        self.assertIn('★ Vibe Coding Legion', result['text'])
        self.assertIn('★ Build', result['text'])
        self.assertIn('Review', result['text'])
        self.assertIn('Coding Agent Index 70', result['text'])
        self.assertNotIn('Other Model', result['text'])


if __name__ == '__main__':
    unittest.main()
