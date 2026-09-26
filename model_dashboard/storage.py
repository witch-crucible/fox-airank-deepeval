from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .domain import DashboardError, calculate_scores, normalize_agent_usage_entry, normalize_model, utc_now
from .leaderboards import compare_snapshot_rows, normalize_third_party_weights
from .recommendations import normalize_recommendations, normalize_stored_recommendations

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
SEED_PATH = ROOT / "seed_data.json"
DEFAULT_DATA_PATH = PROJECT_ROOT / "var" / "sqlite" / f"{PROJECT_ROOT.name}.db"

#: 可单独重建的数据表；写入时只重建真正受影响的表。
TABLES = ("models", "pricing", "agent_usage", "recommendations", "meta")


class DashboardStore:
    def __init__(self, seed_path: Path = SEED_PATH, data_path: Path = DEFAULT_DATA_PATH):
        self.seed_path, self.data_path = Path(seed_path), Path(data_path)
        self.db_path = self.data_path.with_suffix('.db') if self.data_path.suffix in {'.json', '.jsonl'} else self.data_path
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path, timeout=5); con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _initialize(self):
        try:
            with self._connect() as c:
                c.executescript('''CREATE TABLE IF NOT EXISTS models(position INTEGER PRIMARY KEY, model_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pricing(position INTEGER PRIMARY KEY, pricing_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_usage(tool_key TEXT PRIMARY KEY, usage_json TEXT NOT NULL, position INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS recommendations(group_name TEXT PRIMARY KEY, recommendations_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS recommendation_releases(
                    version INTEGER PRIMARY KEY AUTOINCREMENT,
                    published_at TEXT NOT NULL,
                    note TEXT NOT NULL,
                    snapshot_sha256 TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    changes_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_insights(
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    analysis_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS leaderboard_snapshots(
                    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    source_version TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    rows_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS leaderboard_snapshots_source
                    ON leaderboard_snapshots(source_type, snapshot_id DESC);
                CREATE TABLE IF NOT EXISTS model_aliases(
                    alias_key TEXT PRIMARY KEY,
                    canonical_key TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value_json TEXT NOT NULL);''')
                if c.execute('SELECT COUNT(*) FROM models').fetchone()[0] == 0:
                    legacy = self.data_path if self.data_path.suffix.casefold() in {'.json', '.jsonl'} else ROOT / 'data.local.json'
                    source = legacy if legacy.exists() else self.seed_path
                    self._replace(c, self._read_json(source))
                self._seed_leaderboard_snapshots(c)
        except (OSError, sqlite3.Error, json.JSONDecodeError) as e:
            raise DashboardError(f'无法初始化看板数据库：{e}') from e

    @staticmethod
    def _read_json(path):
        try: data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as e: raise DashboardError(f'无法读取看板数据：{e}') from e
        if not isinstance(data, dict) or not isinstance(data.get('models'), list): raise DashboardError('看板数据格式无效')
        return data
    @staticmethod
    def _dump(v): return json.dumps(v, ensure_ascii=False, separators=(',', ':'))
    @staticmethod
    def _load(v): return json.loads(v)

    def _seed_leaderboard_snapshots(self, connection):
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in connection.execute('SELECT model_json FROM models ORDER BY position'):
            model=self._load(row[0]); source_type=self._source_type(model)
            if source_type=='artificial_analysis': source_type='artificial_analysis_agent'
            if source_type in {'arena_webdev','artificial_analysis_agent','artificial_analysis_model','llm_stats'}:
                groups.setdefault(source_type,[]).append(model)
        for source_type,models in groups.items():
            if connection.execute('SELECT 1 FROM leaderboard_snapshots WHERE source_type=? LIMIT 1',(source_type,)).fetchone():
                continue
            source=models[0].get('source',{}) if isinstance(models[0].get('source'),dict) else {}
            rows_json=self._dump(models)
            connection.execute(
                'INSERT INTO leaderboard_snapshots(source_type,fetched_at,source_version,row_count,content_sha256,rows_json) VALUES (?,?,?,?,?,?)',
                (
                    source_type,
                    str(source.get('fetched_at') or source.get('leaderboard_publish_date') or utc_now()),
                    str(source.get('index_version') or source.get('methodology_version') or ''),
                    len(models),
                    hashlib.sha256(rows_json.encode('utf-8')).hexdigest(),
                    rows_json,
                ),
            )

    def _replace(self, c, data, tables=None):
        """重建受影响的表；``tables`` 为空时全量重建。

        单条记录更新只重建对应表，避免为改一行 usage 而重写上千条模型 JSON。
        """
        data = data if isinstance(data, dict) else {}
        targets = set(TABLES if tables is None else tables)
        # __pricing_was_object 必须与 pricing 行同批落库，否则读取时会丢掉定价形态。
        if 'pricing' in targets:
            targets.add('meta')
        for table in TABLES:
            if table in targets:
                c.execute(f'DELETE FROM {table}')
        if 'models' in targets:
            for i, v in enumerate(data.get('models', [])):
                c.execute('INSERT INTO models VALUES (?,?)',(i,self._dump(v)))
        if 'pricing' in targets:
            pricing = data.get('pricing', []); pricing_was_object = isinstance(pricing, dict); pricing = [pricing] if pricing_was_object else pricing
            for i, v in enumerate(pricing if isinstance(pricing,list) else []):
                c.execute('INSERT INTO pricing VALUES (?,?)',(i,self._dump(v)))
            data.setdefault('meta', {})['__pricing_was_object'] = pricing_was_object
        if 'agent_usage' in targets:
            usage = data.get('agent_usage', [])
            if not isinstance(usage, list): usage = []
            for i, v in enumerate(usage):
                if isinstance(v,dict): c.execute('INSERT OR REPLACE INTO agent_usage VALUES (?,?,?)',(str(v.get('tool','')).casefold(),self._dump(v),i))
        if 'recommendations' in targets:
            for group, rows in normalize_stored_recommendations(data.get('recommendations')).items():
                c.execute('INSERT INTO recommendations VALUES (?,?)',(group,self._dump(rows)))
        if 'meta' in targets:
            meta = data.get('meta', {}); meta = meta if isinstance(meta,dict) else {}
            meta = dict(meta)
            meta.setdefault('__pricing_was_object', isinstance(data.get('pricing'), dict))
            for k,v in meta.items(): c.execute('INSERT INTO meta VALUES (?,?)',(k,self._dump(v)))

    def read(self):
        try:
            with self._connect() as c:
                models=[self._load(r[0]) for r in c.execute('SELECT model_json FROM models ORDER BY position')]
                pricing=[self._load(r[0]) for r in c.execute('SELECT pricing_json FROM pricing ORDER BY position')]
                usage=[self._load(r[0]) for r in c.execute('SELECT usage_json FROM agent_usage ORDER BY position')]
                rec={r[0]:self._load(r[1]) for r in c.execute('SELECT group_name,recommendations_json FROM recommendations')}
                meta={r[0]:self._load(r[1]) for r in c.execute('SELECT key,value_json FROM meta')}
                aliases={r[0]:r[1] for r in c.execute('SELECT alias_key,canonical_key FROM model_aliases ORDER BY alias_key')}
            if meta.pop('__pricing_was_object', False) and len(pricing) == 1:
                pricing = pricing[0]
            return {'meta':meta,'models':models,'pricing':pricing,'agent_usage':usage,'recommendations':normalize_stored_recommendations(rec),'model_aliases':aliases}
        except (sqlite3.Error,json.JSONDecodeError,OSError) as e: raise DashboardError(f'无法读取看板数据库：{e}') from e

    def latest_ai_insight(self) -> dict[str, Any] | None:
        try:
            with self._connect() as connection:
                row = connection.execute('SELECT analysis_json FROM ai_insights WHERE id=1').fetchone()
            return self._load(row[0]) if row else None
        except (sqlite3.Error, json.JSONDecodeError, OSError) as error:
            raise DashboardError('无法读取 AI 分析结果') from error

    def save_ai_insight(self, analysis: dict[str, Any]) -> None:
        with self._lock:
            try:
                with self._connect() as connection:
                    connection.execute(
                        'INSERT INTO ai_insights(id,analysis_json) VALUES (1,?) '
                        'ON CONFLICT(id) DO UPDATE SET analysis_json=excluded.analysis_json',
                        (self._dump(analysis),),
                    )
            except (sqlite3.Error, OSError) as error:
                raise DashboardError('无法保存 AI 分析结果') from error

    def write(self, data, tables=None):
        with self._lock:
            try:
                with self._connect() as c:
                    c.execute('BEGIN IMMEDIATE'); self._replace(c,data, tables=tables)
                if self.data_path.suffix.casefold() in {'.json', '.jsonl'}:
                    self.data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            except (sqlite3.Error,OSError,TypeError) as e: raise DashboardError(f'无法写入看板数据库：{e}') from e
    def _mutate(self, fn, tables=None):
        """写入一次变更；``tables`` 限定要重建的表，meta 随 updated_at 一起更新。"""
        with self._lock:
            data=self.read(); result=fn(data); data.setdefault('meta',{})['updated_at']=utc_now()
            self.write(data, tables=(*tables,'meta') if tables else tables)
            return result
    def save_recommendations(self, raw):
        value=normalize_recommendations(raw); self._mutate(lambda d:d.__setitem__('recommendations',value), tables=('recommendations',)); return value

    @classmethod
    def _recommendation_sha256(cls, value: dict[str, Any]) -> str:
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    @staticmethod
    def _recommendation_row_key(row: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(row.get('tool', '')).casefold(),
            str(row.get('model', '')).casefold(),
            str(row.get('reasoning_effort', '')).casefold(),
        )

    @classmethod
    def _recommendation_changes(
        cls,
        previous: dict[str, Any] | None,
        current: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if previous is None:
            return [{
                'type': 'initial',
                'path': 'recommendations',
                'after': {
                    'purpose_types': len(current['purpose_types']),
                    'agent_plan': len(current['agent_plan']),
                    'coding_plan': len(current['coding_plan']),
                },
            }]

        changes: list[dict[str, Any]] = []
        if previous['purpose_types'] != current['purpose_types']:
            changes.append({
                'type': 'update',
                'path': 'purpose_types',
                'before': previous['purpose_types'],
                'after': current['purpose_types'],
            })

        for group in ('agent_plan', 'coding_plan'):
            old_buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
            new_buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
            for row in previous[group]:
                old_buckets.setdefault(cls._recommendation_row_key(row), []).append(row)
            for row in current[group]:
                new_buckets.setdefault(cls._recommendation_row_key(row), []).append(row)
            for identity in sorted(set(old_buckets) | set(new_buckets)):
                old_rows = old_buckets.get(identity, [])
                new_rows = new_buckets.get(identity, [])
                common = min(len(old_rows), len(new_rows))
                display_row = new_rows[0] if new_rows else old_rows[0]
                label = {
                    'tool': str(display_row.get('tool', '')),
                    'model': str(display_row.get('model', '')),
                    'reasoning_effort': str(display_row.get('reasoning_effort', '')),
                }
                for index in range(common):
                    if old_rows[index] != new_rows[index]:
                        fields = sorted(
                            field
                            for field in set(old_rows[index]) | set(new_rows[index])
                            if old_rows[index].get(field) != new_rows[index].get(field)
                        )
                        changes.append({
                            'type': 'update',
                            'path': group,
                            'identity': label,
                            'occurrence': index + 1,
                            'fields': fields,
                            'before': old_rows[index],
                            'after': new_rows[index],
                        })
                for index, row in enumerate(old_rows[common:], start=common + 1):
                    changes.append({
                        'type': 'remove', 'path': group, 'identity': label,
                        'occurrence': index, 'before': row,
                    })
                for index, row in enumerate(new_rows[common:], start=common + 1):
                    changes.append({
                        'type': 'add', 'path': group, 'identity': label,
                        'occurrence': index, 'after': row,
                    })
        return changes

    @staticmethod
    def _release_summary(changes: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            'initial': sum(change['type'] == 'initial' for change in changes),
            'added': sum(change['type'] == 'add' for change in changes),
            'updated': sum(change['type'] == 'update' for change in changes),
            'removed': sum(change['type'] == 'remove' for change in changes),
            'purpose_types_changed': any(change['path'] == 'purpose_types' for change in changes),
        }

    def publish_recommendations(self, raw_note: Any = '') -> dict[str, Any]:
        if not isinstance(raw_note, str):
            raise DashboardError('发布说明必须是字符串')
        note = raw_note.strip()
        if len(note) > 300:
            raise DashboardError('发布说明最多 300 个字符')
        with self._lock:
            try:
                with self._connect() as c:
                    c.execute('BEGIN IMMEDIATE')
                    stored = {
                        row[0]: self._load(row[1])
                        for row in c.execute(
                            'SELECT group_name,recommendations_json FROM recommendations'
                        )
                    }
                    current = normalize_stored_recommendations(stored)
                    latest = c.execute(
                        'SELECT snapshot_json,snapshot_sha256 FROM recommendation_releases '
                        'ORDER BY version DESC LIMIT 1'
                    ).fetchone()
                    current_hash = self._recommendation_sha256(current)
                    if latest is not None and latest['snapshot_sha256'] == current_hash:
                        raise DashboardError('Vibe Coding Legion 与最新发布版本相同，无需重复发布')
                    previous = normalize_stored_recommendations(self._load(latest['snapshot_json'])) if latest else None
                    changes = self._recommendation_changes(previous, current)
                    published_at = utc_now()
                    cursor = c.execute(
                        'INSERT INTO recommendation_releases('
                        'published_at,note,snapshot_sha256,snapshot_json,changes_json'
                        ') VALUES (?,?,?,?,?)',
                        (
                            published_at,
                            note,
                            current_hash,
                            self._dump(current),
                            self._dump(changes),
                        ),
                    )
                    version = int(cursor.lastrowid)
                return {
                    'version': version,
                    'published_at': published_at,
                    'note': note,
                    'snapshot_sha256': current_hash,
                    'changes': changes,
                    'summary': self._release_summary(changes),
                    'recommendations': current,
                }
            except DashboardError:
                raise
            except (sqlite3.Error, json.JSONDecodeError, OSError) as error:
                raise DashboardError(f'无法发布 Vibe Coding Legion：{error}') from error

    def recommendation_releases(self, limit: int = 50) -> dict[str, Any]:
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise DashboardError('发布历史数量必须为 1 至 100')
        try:
            with self._connect() as c:
                stored = {
                    row[0]: self._load(row[1])
                    for row in c.execute(
                        'SELECT group_name,recommendations_json FROM recommendations'
                    )
                }
                current = normalize_stored_recommendations(stored)
                rows = c.execute(
                    'SELECT version,published_at,note,snapshot_sha256,snapshot_json,changes_json '
                    'FROM recommendation_releases ORDER BY version DESC LIMIT ?',
                    (limit,),
                ).fetchall()
            releases = []
            for row in rows:
                changes = self._load(row['changes_json'])
                releases.append({
                    'version': row['version'],
                    'published_at': row['published_at'],
                    'note': row['note'],
                    'snapshot_sha256': row['snapshot_sha256'],
                    'changes': changes,
                    'summary': self._release_summary(changes),
                    'recommendations': normalize_stored_recommendations(self._load(row['snapshot_json'])),
                })
            current_hash = self._recommendation_sha256(current)
            return {
                'is_current': bool(releases and releases[0]['snapshot_sha256'] == current_hash),
                'latest_version': releases[0]['version'] if releases else None,
                'releases': releases,
            }
        except (sqlite3.Error, json.JSONDecodeError, OSError) as error:
            raise DashboardError(f'无法读取建议发布历史：{error}') from error
    def add_model(self, raw):
        if not isinstance(raw,dict): raise DashboardError('模型数据必须是对象')
        safe={k:v for k,v in raw.items() if k not in {'id','source','archived','archived_at'}}; model=normalize_model(safe,source={'type':'manual','name':'手工录入'}); self._mutate(lambda d:d['models'].append(model), tables=('models',)); return model
    def upsert_agent_usage(self, raw):
        entry=normalize_agent_usage_entry(raw); created=True
        def fn(d):
            nonlocal created
            usage=d.setdefault('agent_usage',[])
            for i,v in enumerate(usage):
                if isinstance(v,dict) and str(v.get('tool','')).casefold()==entry['tool'].casefold(): usage[i]=entry; created=False; return
            usage.append(entry)
        self._mutate(fn, tables=('agent_usage',)); return entry,created
    def import_agent_usage(self, entries):
        if not entries: raise DashboardError('没有可导入的使用人数')
        created=updated=0
        def fn(d):
            nonlocal created,updated
            usage=d.setdefault('agent_usage',[]); idx={str(v.get('tool','')).casefold():i for i,v in enumerate(usage) if isinstance(v,dict)}
            for raw in entries:
                v=normalize_agent_usage_entry(raw); key=v['tool'].casefold()
                if key in idx: usage[idx[key]]=v; updated+=1
                else: idx[key]=len(usage); usage.append(v); created+=1
        self._mutate(fn, tables=('agent_usage',)); return {'created':created,'updated':updated,'received':len(entries)}
    def set_model_archived(self, model_id, archived):
        result=None
        def fn(d):
            nonlocal result
            matches=[m for m in d['models'] if m.get('id')==model_id]
            if not matches: raise DashboardError('模型记录不存在')
            if len(matches)>1: raise DashboardError('本地数据包含重复的模型 ID，拒绝修改')
            result=matches[0]; result['archived']=archived; result['archived_at']=utc_now() if archived else ''; result['updated_at']=utc_now()
        self._mutate(fn, tables=('models',)); return result
    def import_models(self, models, overwrite):
        created=updated=skipped=0
        def fn(d):
            nonlocal created,updated,skipped
            idx={self._model_key(m):i for i,m in enumerate(d['models'])}
            for m in models:
                key=self._model_key(m)
                if key in idx:
                    if overwrite:
                        old=d['models'][idx[key]]; m['id']=old.get('id',m['id']); self._preserve_archive(old,m); d['models'][idx[key]]=m; updated+=1
                    else: skipped+=1
                else: idx[key]=len(d['models']); d['models'].append(m); created+=1
        self._mutate(fn, tables=('models',)); return {'created':created,'updated':updated,'skipped':skipped}

    def _sync(self, models, typ, key, meta, legacy_types=()):
        if not models:
            raise DashboardError('榜单没有可保存的数据')
        created=updated=0
        all_types={typ,*legacy_types}
        with self._lock:
            data=self.read()
            old={key(m):m for m in data['models'] if self._source_type(m) in all_types}
            retained=[m for m in data['models'] if self._source_type(m) not in all_types]
            seen=set()
            for model in models:
                identity=key(model); seen.add(identity); previous=old.get(identity)
                if previous:
                    model['id']=previous.get('id',model['id']); self._preserve_archive(previous,model); updated+=1
                else:
                    created+=1
                retained.append(model)
            retained.extend(model for identity,model in old.items() if identity not in seen and model.get('archived') is True)
            data['models']=retained
            data.setdefault('meta',{}).update(meta)
            data['meta']['updated_at']=utc_now()
            rows_json=self._dump(models)
            source= models[0].get('source',{}) if isinstance(models[0].get('source'),dict) else {}
            source_version=str(source.get('index_version') or source.get('methodology_version') or '')
            digest=hashlib.sha256(rows_json.encode('utf-8')).hexdigest()
            try:
                with self._connect() as connection:
                    connection.execute('BEGIN IMMEDIATE')
                    self._replace(connection,data)
                    connection.execute(
                        'INSERT INTO leaderboard_snapshots(source_type,fetched_at,source_version,row_count,content_sha256,rows_json) VALUES (?,?,?,?,?,?)',
                        (typ,str(source.get('fetched_at') or utc_now()),source_version,len(models),digest,rows_json),
                    )
                if self.data_path.suffix.casefold() in {'.json','.jsonl'}:
                    self.data_path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            except (sqlite3.Error,OSError,TypeError) as error:
                raise DashboardError(f'无法保存榜单快照：{error}') from error
        return {'created':created,'updated':updated,'removed':0}
    def sync_arena_webdev(self, models): return self._sync(models,'arena_webdev',lambda m:str(m.get('model','')).casefold(),{'arena_webdev_updated_at':models[0]['source']['fetched_at'],'arena_webdev_publish_date':models[0]['source'].get('leaderboard_publish_date','')})
    def sync_artificial_analysis(self, models): return self._sync(models,'artificial_analysis_agent',lambda m:str(m['source']['source_id']),{'artificial_analysis_updated_at':models[0]['source']['fetched_at'],'artificial_analysis_index_version':models[0]['source']['index_version']},legacy_types=('artificial_analysis',))
    def sync_artificial_analysis_models(self, models): return self._sync(models,'artificial_analysis_model',lambda m:str(m['source']['source_id']),{'artificial_analysis_models_updated_at':models[0]['source']['fetched_at'],'artificial_analysis_models_index_version':models[0]['source']['index_version']})
    def sync_llm_stats(self, models): return self._sync(models,'llm_stats',lambda m:str(m['source']['source_id']),{'llm_stats_updated_at':models[0]['source']['fetched_at']})

    def leaderboard_snapshots(self, source_type, limit=50):
        allowed={'arena_webdev','artificial_analysis_model','artificial_analysis_agent','llm_stats'}
        if source_type not in allowed:
            raise DashboardError('榜单来源无效')
        if not isinstance(limit,int) or limit<1 or limit>200:
            raise DashboardError('快照条数必须在 1 到 200 之间')
        try:
            with self._connect() as connection:
                rows=connection.execute(
                    'SELECT snapshot_id,source_type,fetched_at,source_version,row_count,content_sha256 FROM leaderboard_snapshots WHERE source_type=? ORDER BY snapshot_id DESC LIMIT ?',
                    (source_type,limit),
                ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as error:
            raise DashboardError(f'无法读取榜单快照：{error}') from error

    def leaderboard_comparison(self, source_type, snapshot_id=None, compare_id=None):
        snapshots=self.leaderboard_snapshots(source_type,200)
        if not snapshots:
            return {'source_type':source_type,'snapshots':[],'current':None,'compare':None,'rows':[]}
        ids=[row['snapshot_id'] for row in snapshots]
        current_id=int(snapshot_id) if snapshot_id is not None else ids[0]
        if current_id not in ids:
            raise DashboardError('当前榜单快照不存在')
        current_index=ids.index(current_id)
        default_compare=ids[current_index+1] if current_index+1<len(ids) else None
        previous_id=int(compare_id) if compare_id not in (None,'') else default_compare
        if previous_id is not None and previous_id not in ids:
            raise DashboardError('对照榜单快照不存在')
        try:
            with self._connect() as connection:
                current_row=connection.execute('SELECT * FROM leaderboard_snapshots WHERE snapshot_id=?',(current_id,)).fetchone()
                previous_row=connection.execute('SELECT * FROM leaderboard_snapshots WHERE snapshot_id=?',(previous_id,)).fetchone() if previous_id else None
            current_models=self._load(current_row['rows_json'])
            previous_models=self._load(previous_row['rows_json']) if previous_row else []
            comparable=not previous_row or current_row['source_version']==previous_row['source_version'] or not current_row['source_version'] or not previous_row['source_version']
            return {
                'source_type':source_type,
                'snapshots':snapshots,
                'current':{key:current_row[key] for key in ('snapshot_id','fetched_at','source_version','row_count')},
                'compare':{key:previous_row[key] for key in ('snapshot_id','fetched_at','source_version','row_count')} if previous_row else None,
                'rows':compare_snapshot_rows(current_models,previous_models,comparable=comparable),
                'comparable':comparable,
            }
        except (sqlite3.Error,json.JSONDecodeError) as error:
            raise DashboardError(f'无法对比榜单快照：{error}') from error

    def save_model_alias(self, alias_key, canonical_key):
        alias=str(alias_key or '').strip().casefold(); canonical=str(canonical_key or '').strip().casefold()
        if not alias or not canonical:
            raise DashboardError('模型别名和标准名称不能为空')
        if len(alias)>200 or len(canonical)>200:
            raise DashboardError('模型别名或标准名称过长')
        try:
            with self._lock,self._connect() as connection:
                connection.execute('BEGIN IMMEDIATE')
                connection.execute(
                    'INSERT OR REPLACE INTO model_aliases(alias_key,canonical_key,updated_at) VALUES (?,?,?)',
                    (alias,canonical,utc_now()),
                )
            return {'alias_key':alias,'canonical_key':canonical}
        except sqlite3.Error as error:
            raise DashboardError(f'无法保存模型关联：{error}') from error
    def leaderboard_weights(self, data=None):
        """读取三方权重；已调用过 read() 时可直接复用数据，避免重复全库读取。"""
        if data is None:
            data=self.read()
        return normalize_third_party_weights(data.get('meta',{}).get('leaderboard_weights'))
    def save_leaderboard_weights(self, raw):
        weights=normalize_third_party_weights(raw)
        self._mutate(lambda data:data.setdefault('meta',{}).__setitem__('leaderboard_weights',weights), tables=('meta',))
        return weights
    def sync_benchmark(self, models):
        created=updated=0
        def fn(d):
            nonlocal created,updated
            idx={self._benchmark_key(m):i for i,m in enumerate(d['models'])}
            for m in models:
                k=self._benchmark_key(m)
                if k in idx:
                    old=d['models'][idx[k]]; self._preserve_archive(old,m)
                    for f in ('model_test_correction','model_test_generation','model_test_logic'): old['scores'][f]=m['scores'].get(f)
                    old['scores']=calculate_scores(old['scores']); old['report_path']=m.get('report_path',old.get('report_path','')); old['updated_at']=utc_now(); updated+=1
                else: d['models'].append(m); created+=1
            d.setdefault('meta',{})['benchmark_updated_at']=utc_now()
            if models: d['meta']['benchmark_run_id']=str(models[0].get('source',{}).get('run_id',''))
        self._mutate(fn); return {'created':created,'updated':updated,'skipped':0}
    @staticmethod
    def _source_type(m):
        s=m.get('source'); return str(s.get('type','')) if isinstance(s,dict) else ''
    @staticmethod
    def _preserve_archive(old,new): new['archived']=old.get('archived') is True; new['archived_at']=old.get('archived_at','') if new['archived'] else ''
    @staticmethod
    def _model_key(m): return (str(m.get('tool','')).casefold(),str(m.get('model','')).casefold(),str(m.get('reasoning_effort','')).casefold())
    @staticmethod
    def _benchmark_key(m): return (str(m.get('tool','')).casefold(),str(m.get('model','')).casefold())
