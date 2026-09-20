import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from model_dashboard.domain import DashboardError, normalize_model
from model_dashboard.server import create_server


class LegionRefreshTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        seed = root / 'seed.json'
        self.recommendations = {
            'purpose_types': ['Build'],
            'agent_plan': [{
                'tool': 'Codex', 'model': 'Alpha', 'reasoning_effort': '高',
                'primary_purpose_types': ['Build'], 'core_purpose_types': ['Build'],
            }],
            'coding_plan': [],
        }
        seed.write_text(json.dumps({'models': [], 'recommendations': self.recommendations}))
        self.server = create_server('127.0.0.1', 0, data_path=seed, runs_root=root / 'runs')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, path, payload=None):
        request = Request(self.url + path, data=json.dumps(payload).encode() if payload is not None else None,
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def record(self, source, effort='high', score=60):
        field = {'arena_webdev': 'arena_webdev', 'artificial_analysis_model': 'aa_model_intelligence',
                 'llm_stats': 'llm_stats_score', 'artificial_analysis_agent': 'artificial_analysis_index'}[source]
        return normalize_model(
            {'tool': 'Codex' if source.endswith('_agent') else 'Lab', 'model': 'Alpha',
             'reasoning_effort': effort, 'scores': {field: score}},
            source={'type': source, 'source_id': source + '-' + effort, 'rank': 1,
                    'fetched_at': '2026-09-21T00:00:00Z', 'index_version': 'v1'},
        )

    def test_get_routes_include_legion_identity_and_core_state(self):
        model = self.request('/api/leaderboards/models')['models'][0]
        agent = self.request('/api/leaderboards/agents')['agents'][0]
        for row in (model, agent):
            self.assertTrue(row['legion']['matched'])
            self.assertTrue(row['legion']['is_core'])
            self.assertTrue(row['supplemental'])
        self.assertEqual(model['reasoning_effort'], 'high')
        self.assertIsNone(model['third_party_score'])
        self.assertIsNone(agent['agent']['scores'].get('artificial_analysis_index'))

    def test_refresh_fetches_only_missing_sources_and_fuses_matching_results(self):
        store = self.server.store
        store.sync_arena_webdev([self.record('arena_webdev')])
        calls = []

        def fake_sync(handler, source):
            calls.append(source)
            record = self.record(source, 'unknown' if source == 'llm_stats' else 'high')
            method = {'artificial_analysis_model': store.sync_artificial_analysis_models,
                      'artificial_analysis_agent': store.sync_artificial_analysis,
                      'llm_stats': store.sync_llm_stats}[source]
            method([record])
            return {'received': 1, 'created': 1, 'updated': 0, 'removed': 0}

        with patch('model_dashboard.server.DashboardHandler._sync_leaderboard', new=fake_sync):
            result = self.request('/api/leaderboards/legion/refresh', {})
        self.assertEqual(calls, ['artificial_analysis_model', 'llm_stats', 'artificial_analysis_agent'])
        self.assertEqual(result['missing_models'], [{'model': 'Alpha', 'reasoning_effort': 'high', 'sources': ['llm_stats']}])
        self.assertEqual(result['missing_agents'], [])
        rows = self.request('/api/leaderboards/models')['models']
        high = next(row for row in rows if row['reasoning_effort'] == 'high')
        self.assertEqual(high['sources']['artificial_analysis_model']['raw_score'], 60)
        self.assertNotIn('llm_stats', high['sources'])
        self.assertIsNone(high['third_party_score'])

    def test_refresh_continues_after_failure_and_preserves_stored_scores(self):
        store = self.server.store
        store.sync_artificial_analysis_models([self.record('artificial_analysis_model', 'max', 99)])
        calls = []

        def fake_sync(handler, source):
            calls.append(source)
            if source == 'artificial_analysis_model':
                raise DashboardError('测试来源暂时不可用')
            return {'received': 0, 'created': 0, 'updated': 0, 'removed': 0}

        with patch('model_dashboard.server.DashboardHandler._sync_leaderboard', new=fake_sync):
            result = self.request('/api/leaderboards/legion/refresh', {})
        self.assertEqual(len(calls), 4)
        self.assertEqual(result['sources'][0]['status'], 'failed')
        self.assertEqual(store.read()['models'][0]['scores']['aa_model_intelligence'], 99)
        high = next(row for row in self.request('/api/leaderboards/models')['models'] if row['reasoning_effort'] == 'high')
        self.assertEqual(high['sources'], {})

    def test_complete_configuration_does_not_refetch(self):
        store = self.server.store
        for source, sync in [('arena_webdev', store.sync_arena_webdev),
                             ('artificial_analysis_model', store.sync_artificial_analysis_models),
                             ('llm_stats', store.sync_llm_stats),
                             ('artificial_analysis_agent', store.sync_artificial_analysis)]:
            sync([self.record(source)])
        with patch('model_dashboard.server.DashboardHandler._sync_leaderboard') as sync:
            result = self.request('/api/leaderboards/legion/refresh', {})
        sync.assert_not_called()
        self.assertEqual(result, {'sources': [], 'missing_models': [], 'missing_agents': []})


if __name__ == '__main__':
    unittest.main()
