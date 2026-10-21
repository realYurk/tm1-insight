"""Bounded presentation of existing relation indexes; never a new semantic parser.

An index row is an observation, not a confirmed cell-value dependency. Workspace
annotations are deliberately stored outside DuckDB and cannot promote that status.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from tm1_insight.domain.model import Dependency, DependencyKind
from tm1_insight.lineage.engine import build_adjacency, get_downstream
from tm1_insight.design import Design

VERSION = 'architecture-workspace-3'


def stable_id(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:32]


class ObjectRef(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['cube', 'process', 'chore', 'dimension'] = 'cube'
    name: str = Field(min_length=1, max_length=1000)


class GraphQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    snapshot_id: str = Field(default='', max_length=128)
    objects: list[ObjectRef] = Field(default_factory=list, max_length=120)
    source_prefix: str = Field(default='', max_length=200)
    target_prefix: str = Field(default='', max_length=200)
    seed_offset: int = Field(default=0, ge=0, le=100000, strict=True)
    direction: Literal['upstream', 'downstream', 'both'] = 'both'
    depth: int = Field(default=2, ge=0, le=6, strict=True)
    node_budget: int = Field(default=60, ge=2, le=120, strict=True)
    edge_budget: int = Field(default=160, ge=1, le=300, strict=True)
    view: Literal['cubes', 'objects'] = 'cubes'
    include_technical: bool = False
    relation_types: list[Literal['TI_READ', 'TI_WRITE', 'TI_CANDIDATE', 'RULE_REFERENCE', 'FEEDER_REFERENCE', 'CALL', 'SCHEDULE', 'STRUCTURE']] = Field(default_factory=list, max_length=8)


# Tables already maintained by the collector / existing parsers. No source loads.
INDEXES = (
    ('process_reads_cube', 'cube_name', 'process_name', 'cube', 'process', 'TI_READ', '读取'),
    ('process_writes_cube', 'process_name', 'cube_name', 'process', 'cube', 'TI_WRITE', '写入'),
    ('process_calls_process', 'caller', 'callee', 'process', 'process', 'CALL', '调用'),
    # This legacy index includes comments and feeders. Discovery only; it MUST
    # be replaced by the existing semantic IR before any public graph projection.
    ('rule_references_cube', 'source_cube', 'cube_name', 'cube', 'cube', 'RULE_SOURCE_REFERENCE', '待核对的文件引用'),
    ('chore_runs_process', 'chore_name', 'process_name', 'chore', 'process', 'SCHEDULE', '调度'),
    ('cube_has_dimension', 'cube_name', 'dimension_name', 'cube', 'dimension', 'STRUCTURE', '维度结构'),
)


def indexed_graph(con, snapshot):
    nodes, edges = {}, {}

    def node(kind, name, present=False):
        key = stable_id(snapshot, kind, name)
        if key not in nodes:
            nodes[key] = dict(id=key, type=kind, name=name, provenance='MODEL_FACT' if present else 'STATIC_ANALYSIS',
                              in_snapshot=present, snapshot_id=snapshot)
        return key

    for kind, table in [('cube', 'cubes'), ('process', 'processes'), ('chore', 'chores'), ('dimension', 'dimensions')]:
        for (name,) in con.execute('SELECT name FROM ' + table + ' ORDER BY name').fetchall():
            node(kind, name, present=True)
    for table, sc, tc, st, tt, kind, label in INDEXES:
        order = 'step_order' if kind=='SCHEDULE' else 'dim_order' if kind=='STRUCTURE' else None
        cols = f'{sc},{tc}' + (','+order if order else '')
        for row in con.execute(f'SELECT DISTINCT {cols} FROM {table} ORDER BY 1,2' + (',3' if order else '')).fetchall():
            source, target = row[:2]
            sid, tid = node(st, source), node(tt, target)
            key = stable_id(snapshot, sid, tid, kind, row[2]) if order else stable_id(snapshot, sid, tid, kind)
            evidence = dict(table=table, source=source, target=target)
            if order: evidence[order]=row[2]
            edges[key] = dict(id=key, source=sid, target=tid, kind=kind, label=label,
                              provenance='STATIC_ANALYSIS', status='INDEX_OBSERVATION', runtime_verified=False,
                              evidence=[evidence],
                              unresolved_reasons=['索引级关系；精确切面、源码位置与值依赖需在详情核对。'])
    return nodes, list(edges.values())


def query_graph(index, query: GraphQuery, snapshot, *, discovery=False):
    nodes, raw = index
    if not query.include_technical:
        hidden = {k for k,n in nodes.items() if n['name'].startswith('}')}
        raw = [e for e in raw if e['source'] not in hidden and e['target'] not in hidden]
    edges = raw
    # Cube-first projection only aggregates actual indexed co-access. This is
    # deliberately called CANDIDATE and never a confirmed transfer / value flow.
    if query.view == 'cubes' and not any(o.type != 'cube' for o in query.objects):
        readers, writers = {}, {}
        for e in raw:
            if e['kind'] == 'TI_READ': readers.setdefault(e['target'], []).append(e)
            if e['kind'] == 'TI_WRITE': writers.setdefault(e['source'], []).append(e)
        candidates = {}
        # Build only candidates touching bounded query scope later: each process
        # pair is capped; large fan-out is reported as a limit, never materialized.
        candidate_cut = False
        for process in sorted(readers.keys() & writers.keys()):
            for read in readers[process]:
                for write in writers[process]:
                    if len(candidates) >= 50000:
                        candidate_cut = True
                        break
                    key=(read['source'],write['target'])
                    edge=candidates.setdefault(key,dict(id=stable_id(snapshot, *key, 'TI_CANDIDATE'),
                        source=read['source'], target=write['target'], kind='TI_CANDIDATE',
                        label='共同读写 · 待核对值流', process_ids=[], process_names=[], provenance='STATIC_ANALYSIS',
                        status='CANDIDATE', runtime_verified=False,
                        evidence=[], unresolved_reasons=['同一 TI 读取并写入；尚未证明源值与目标值一一对应。']))
                    edge['process_ids'].append(process);edge['process_names'].append(nodes[process]['name'])
                    edge['evidence'] += read['evidence'] + write['evidence']
                if candidate_cut: break
            if candidate_cut: break
        for edge in candidates.values():
            if len(edge['process_ids']) == 1:
                edge.update(process_id=edge['process_ids'][0],process_name=edge['process_names'][0])
            else: edge['label']=str(len(edge['process_ids']))+' 个 TI 共同读写 · 值流待核对'
        edges = [e for e in raw if e['kind'] in ({'RULE_SOURCE_REFERENCE','RULE_REFERENCE','FEEDER_REFERENCE'} if discovery else {'RULE_REFERENCE','FEEDER_REFERENCE'})] + list(candidates.values())
    else:
        candidate_cut = False
        if not query.relation_types:
            edges = [e for e in edges if e['kind'] != 'STRUCTURE']
    if not discovery:
        edges = [e for e in edges if e['kind'] != 'RULE_SOURCE_REFERENCE']
    if not query.include_technical and 'FEEDER_REFERENCE' not in query.relation_types:
        edges = [e for e in edges if e['kind'] != 'FEEDER_REFERENCE']
    if query.relation_types:
        edges = [e for e in edges if e['kind'] in query.relation_types]
    seeds = [stable_id(snapshot, o.type, o.name) for o in query.objects]
    missing = [o.model_dump() for o, key in zip(query.objects, seeds) if key not in nodes]
    seeds = [s for s in seeds if s in nodes]
    prefix = query.source_prefix.rstrip('*').casefold()
    matches = sorted((n for n in nodes.values() if n['type'] == 'cube' and prefix and n['name'].casefold().startswith(prefix)), key=lambda n:n['name'])
    seeds = sorted(set(seeds + [n['id'] for n in matches[query.seed_offset:query.seed_offset+20]]))
    if not seeds:
        return dict(schema=VERSION, snapshot_id=snapshot, nodes=[], edges=[], query=query.model_dump(),
                    limits=dict(truncated=False, missing=missing, prefix_matches=len(matches)), paths=[],
                    limitations=['未找到入口；名称前缀不构成关系证据。'])
    deps = [Dependency(DependencyKind.OTHER, e['source'], e['target'], metadata={'edge_id':e['id']}) for e in edges]
    forward = build_adjacency(deps)
    reverse = build_adjacency([Dependency(d.kind, d.target, d.source, metadata=d.metadata) for d in deps])
    selected = set(seeds[:query.node_budget]); path_ids = set(); paths = []; traversed_pairs = set()
    by_edge = {e['id']:e for e in edges}
    target = query.target_prefix.rstrip('*').casefold()
    for seed in seeds:
        for adj in ([forward] if target or query.direction == 'downstream' else [reverse] if query.direction == 'upstream' else [forward, reverse]):
            for path in get_downstream([], seed, _adj=adj, max_depth=query.depth, max_nodes=query.node_budget):
                if target and not nodes[path.target]['name'].casefold().startswith(target): continue
                if target and nodes[path.target]['type'] != 'cube': continue
                if len(selected | set(path.path)) > query.node_budget: continue
                selected.update(path.path)
                for dep in path.dependencies:
                    edge = by_edge[dep.metadata['edge_id']]
                    traversed_pairs.add((edge['source'],edge['target']))
                if target:
                    path_ids.update(d.metadata['edge_id'] for d in path.dependencies)
                    if len(paths) < 100: paths.append(list(path.path))
    visible = [e for e in edges if e['source'] in selected and e['target'] in selected
               and (query.depth == 0 or (e['source'],e['target']) in traversed_pairs)
               and (not target or e['id'] in path_ids)]
    visible.sort(key=lambda e:(e['source'],e['target'],e['kind'],e['id']))
    boundary = any((e['source'] in selected) != (e['target'] in selected) for e in edges)
    # 「预算截断」与「局部视图边界」是两件事：边界外仍有对象是局部探索的常态，
    # 只有真正因预算丢弃了结果才标记 truncated，否则该标志将恒为真而失去意义。
    truncated = bool(candidate_cut or len(matches)>query.seed_offset+20
                     or len(visible)>query.edge_budget or len(paths)>=100
                     or len(selected)>=query.node_budget)
    return dict(schema=VERSION, snapshot_id=snapshot, nodes=[nodes[k] for k in sorted(selected)],
                edges=visible[:query.edge_budget], query=query.model_dump(), paths=paths,
                limits=dict(truncated=truncated,
                            next_seed_offset=query.seed_offset+20 if len(matches)>query.seed_offset+20 else None,
                            paths_truncated=len(paths)>=100,
                            missing=missing, prefix_matches=len(matches), boundary=boundary),
                limitations=['局部索引探索，不代表完整模型或运行顺序。', '规则引用、共同读写、调用和结构关系保留不同语义；静态路径不是已验证的值流。'])


class Group(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    name: str = Field(min_length=1, max_length=200)
    members: list[str] = Field(default_factory=list, max_length=120)
    note: str = Field(default='', max_length=10000)
    folded: bool = False
    provenance: Literal['USER_INTERPRETATION'] = 'USER_INTERPRETATION'


class DraftCube(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^draft-[a-zA-Z0-9_-]{1,64}$')
    name: str = Field(min_length=1, max_length=200)
    dimensions: list[str] = Field(min_length=1, max_length=100)
    provenance: Literal['DESIGN_DRAFT'] = 'DESIGN_DRAFT'

    @model_validator(mode='after')
    def dimension_order(self):
        if any(not d.strip() or len(d)>200 for d in self.dimensions) or len({d.casefold() for d in self.dimensions})!=len(self.dimensions):
            raise ValueError('Draft dimensions must be nonempty, unique names in declared order')
        return self


class Workspace(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['architecture-workspace-1', 'architecture-workspace-2',
                            'architecture-workspace-3'] = VERSION
    snapshot_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    query: GraphQuery = Field(default_factory=GraphQuery)
    objects: list[ObjectRef] = Field(default_factory=list, max_length=120)
    selected: list[str] = Field(default_factory=list, max_length=120)
    visible: list[str] = Field(default_factory=list, max_length=120)
    edge_ids: list[str] = Field(default_factory=list, max_length=300)
    hidden: list[str] = Field(default_factory=list, max_length=120)
    groups: list[Group] = Field(default_factory=list, max_length=40)
    drafts: list[DraftCube] = Field(default_factory=list, max_length=40)
    notes: str = Field(default='', max_length=30000)
    mdx: str = Field(default='', max_length=30000)
    layout: dict[str, float] = Field(default_factory=dict, max_length=5)
    # 画布节点坐标（仅展示用途；不改变任何关系语义）
    positions: dict[str, dict[str, float]] = Field(default_factory=dict, max_length=400)
    template_ref: Literal['', 'cube-data-transfer'] = ''
    design: Design = Field(default_factory=Design)

    @model_validator(mode='after')
    def references(self):
        if self.query.snapshot_id and self.query.snapshot_id != self.snapshot_id:
            raise ValueError('Query snapshot differs from workspace')
        if len({g.id for g in self.groups}) != len(self.groups): raise ValueError('Duplicate group id')
        if len({d.id for d in self.drafts}) != len(self.drafts): raise ValueError('Duplicate draft id')
        valid = ({stable_id(self.snapshot_id, o.type, o.name) for o in self.objects}
                 | {d.id for d in self.drafts}
                 | {c.id for c in self.design.cubes}
                 | {s.id for s in self.design.schemas})
        refs = set(self.selected + self.visible + self.hidden + [m for g in self.groups for m in g.members])
        if refs - valid: raise ValueError('Workspace contains dangling object references')
        if set(self.layout) - {'zoom','x','y','vertical'} or any(not (-1e6 < v < 1e6) for v in self.layout.values()):
            raise ValueError('Invalid viewport')
        return self


_save_lock = threading.Lock()


def load_workspace(root: Path, key: str):
    if not re.fullmatch(r'[a-f0-9]{32}', key): raise ValueError('Invalid workspace id')
    data = (root / (key + '.json')).read_bytes()
    if len(data) > 1024*1024: raise ValueError('Workspace exceeds size budget')
    return Workspace.model_validate_json(data), hashlib.sha256(data).hexdigest()


def save_workspace(root: Path, key: str, workspace: Workspace, expected: str):
    if not re.fullmatch(r'[a-f0-9]{32}', key): raise ValueError('Invalid workspace id')
    root.mkdir(parents=True, exist_ok=True)
    path = root / (key + '.json')
    data = workspace.model_dump_json(indent=2).encode('utf-8')
    if len(data) > 1024*1024: raise ValueError('Workspace exceeds size budget')
    with _save_lock:
        if path.exists():
            old = path.read_bytes()
            if hashlib.sha256(old).hexdigest() != expected: raise FileExistsError('工作区已变化，请重新加载或另存，未覆盖旧版本。')
        elif expected: raise FileExistsError('工作区已不存在，请另存。')
        fd, temp = tempfile.mkstemp(dir=root, prefix='.workspace-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            if path.exists():
                # A single recoverable predecessor, never a model snapshot copy.
                backup = path.with_suffix('.json.bak')
                with backup.open('wb') as stream:
                    stream.write(old); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp): os.unlink(temp)
    return hashlib.sha256(data).hexdigest()
