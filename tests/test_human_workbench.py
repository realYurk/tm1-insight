"""Human presentation keeps old evidence, uncertainty, routes and source boundaries."""
import hashlib
import io
import json
import subprocess
import time
import zipfile
from pathlib import Path

import pytest
from tm1_insight import architecture
from tm1_insight.config import Settings
from tm1_insight.human_workbench import flow,rule_page
from tm1_insight.functional_flow import markdown,mermaid
from tm1_insight.workbench_export import package,stream,redact_source
from tm1_insight.store.queries import process_graph_rich
from test_architecture import con, fixture  # noqa: F401
from test_datasource_api import client  # noqa: F401


@pytest.fixture
def artifact(con,tmp_path):
    con.execute("UPDATE cubes SET rules=?,has_rules=true WHERE name='Cube_B'",["['Measure':'Member1']=N:IF(1=1,DB('Cube_A',!Year,'Member1')+DB('Cube_A',!Year,pMember),DB(pCube,!Year));\nFEEDERS;[]=>DB('Cube_A',!Year,'Member1');"])
    result=architecture.artifact(architecture.build(con,'Load'),tmp_path)
    yield result.path
    result.cleanup()


def test_rule_rows_one_statement_not_per_reference_and_ir_only_on_demand(artifact):
    result=rule_page(artifact)
    assert result['total']==1
    row=result['items'][0]
    assert row['cube']=='Cube_B' and row['line']==1 and row['has_if']
    assert row['sources']==['Cube_A'] and row['details']['unconfirmed_references']==1
    assert row['context_ref']=='/rules/0/rule_semantics/0'
    assert row['fixed_slices'][0]['dimension']=='Measure'
    assert 'expression_ir' not in json.dumps(result)
    assert rule_page(artifact,q='not-present')['total']==0
    assert rule_page(artifact,offset=1)['items']==[]


def test_naked_rule_members_do_not_gain_dimension_ownership(con,tmp_path):
    con.execute("UPDATE cubes SET rules='[''Member1'']=1;',has_rules=true WHERE name='Cube_B'")
    art=architecture.artifact(architecture.build(con,'Load'),tmp_path)
    try:assert rule_page(art.path)['items'][0]['fixed_slices']==[]
    finally:art.cleanup()


def test_human_markdown_flow_and_mermaid_share_objects_and_actions(artifact):
    result=flow(artifact);text=''.join(markdown(result,include_evidence=False))
    assert text.index('```mermaid')<text.index('## 对象与作用')<text.index('## 动作与关键切面')
    assert '## 核心 Rule 摘要' in text and '重要限制' in text
    assert 'SOURCE_CONFIRMED' not in text and 'UNKNOWN' not in text and 'expression_ir' not in text
    assert mermaid(result) in text
    assert result['rule_rows_total']==1


def test_ai_package_checksums_sources_metadata_missing_and_stability(con,artifact):
    before=con.execute('SELECT prolog FROM processes WHERE name=?',['Load']).fetchone()
    data=b''.join(stream(package(artifact,con)))
    assert data==b''.join(stream(package(artifact,con)))
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        manifest=json.loads(z.read('Manifest.json'))
        assert manifest['schema']=='tm1-analysis-package-1' and not manifest['runtime_verified']
        assert len(manifest['files'])==len(z.namelist())-1
        for entry in manifest['files']:
            content=z.read(entry['path'])
            assert len(content)==entry['bytes'] and hashlib.sha256(content).hexdigest()==entry['sha256']
        source=json.loads(z.read(next(s['path'] for s in manifest['sources'] if s['name']=='Load')))
        assert not source['recorded_metadata']['recorded']
        assert source['sections']['prolog']==before[0]
        assert 'Rule' not in source['sections']
        analysis=json.loads(z.read('Architecture.json'))
        assert analysis['rules'][0]['rule_semantics'][0]['rhs']['expression_ir']
        assert analysis['rules'][0]['feeder_semantics']
        dimensions=[e['path'] for e in manifest['files'] if e['kind']=='dimension_summary']
        assert dimensions
        dim=json.loads(z.read(dimensions[0]))
        assert dim['summary']['elements']['total']==120
        assert len(dim['summary']['elements']['sample'])==25
        assert not dim['summary']['elements']['complete']
    assert con.execute('SELECT prolog FROM processes WHERE name=?',['Load']).fetchone()==before


def test_ai_package_redacts_credentials_without_destroying_source_locations(con,tmp_path):
    code="password='synthetic-secret';\n# password=hidden\nODBCOpen('dsn','user','another-secret');\nCellPutN(1,'Cube_B',vYear,pRegion,pMeasure);"
    con.execute("UPDATE processes SET prolog=? WHERE name='Load'",[code])
    art=architecture.artifact(architecture.build(con,'Load'),tmp_path)
    try:
        payload=b''.join(stream(package(art.path,con,settings=Settings(tm1_password='synthetic-secret'))))
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            assert b'synthetic-secret' not in b''.join(z.read(n) for n in z.namelist())
            assert b'another-secret' not in b''.join(z.read(n) for n in z.namelist())
            manifest=json.loads(z.read('Manifest.json'))
            src=json.loads(z.read(next(s['path'] for s in manifest['sources'] if s['name']=='Load')))
            assert len(src['sections']['prolog'])==len(code)
            assert src['sections']['prolog'].count('\n')==code.count('\n')
            assert "CellPutN(1,'Cube_B'" in src['sections']['prolog']
            assert manifest['credential_redactions']>0
    finally:art.cleanup()


def test_source_redaction_preserves_literals_outside_credential_context():
    source="DataSourceNameForServer='Cube_A';\nDataSourcePassword='bad';\nCellPutN(1,'Cube_B',pYear);"
    out,count=redact_source(source)
    assert count==1 and "'bad'" not in out and "'Cube_A'" in out and "'Cube_B'" in out
    assert len(source)==len(out)


def test_failed_package_never_publishes_mismatched_or_oversized_sources(con,artifact,monkeypatch):
    con.execute("UPDATE processes SET data='changed;' WHERE name='Load'")
    with pytest.raises(ValueError,match='源码'):package(artifact,con)
    import tm1_insight.workbench_export as exporter
    monkeypatch.setattr(exporter,'MAX_BYTES',10)
    with pytest.raises(ValueError,match='预算'):package(artifact,con)


def test_graph_global_budget_cycles_and_stable_order(con):
    for i in range(40):con.execute('INSERT INTO process_calls_process VALUES (?,?)',['Load',f'Child{i:02d}'])
    a=process_graph_rich(con,'Load',max_nodes=12,max_depth=4)
    assert a==process_graph_rich(con,'Load',max_nodes=12,max_depth=4)
    def count(items):return sum(1+count(n.get('children',[])) for n in items)
    assert count(a['callers'])+count(a['callees'])+1<=12
    assert a['budget']['truncated'] and a['budget']['nodes']<=12
    assert process_graph_rich(con,'Load',max_depth=0)['callers']==[]


def test_rule_source_default_open_before_semantics_and_feeders(client):
    page=client.get('/explorer/cube/Sales').text
    assert 'details open class="rule-raw"' in page
    assert page.index('class="rule-raw"')<page.index('class="rule-analysis"')
    assert 'data-highlight="rules"' in page and 'syntax.js?v=' in page


def test_defaults_routes_exports_rule_summary_and_graph_lazy_slice(client):
    assert 'data-view="functional_flow"' in client.get('/architecture').text
    response=client.post('/api/architecture/tasks',json={'process':'Load_Sales'})
    task=response.json()['task_id'];base='/api/architecture/tasks/'+task
    deadline=time.monotonic()+12
    while client.get(base).json()['status'] in {'queued','running'}:
        assert time.monotonic()<deadline;time.sleep(.02)
    assert client.get(base+'/rule-table').status_code==200
    assert client.get(base+'/export?format=human-markdown').status_code==200
    ai=client.get(base+'/export?format=ai-package')
    assert ai.status_code==200
    with zipfile.ZipFile(io.BytesIO(ai.content)) as z:assert 'Manifest.json' in z.namelist()
    graph=client.get('/graph?ti=Load_Sales&depth=1&nodes=10')
    # The TI page now lazily uses the existing Workflow job's independent
    # writes, replacing the legacy Formation-summary DOM hook. Keep the route,
    # scope controls and technical Formation entry covered rather than require
    # an obsolete rendering implementation.
    assert graph.status_code==200 and 'id="tr-root"' in graph.text
    assert 'data-depth="1"' in graph.text and 'data-budget="10"' in graph.text
    assert 'Formation 加工证据' in graph.text
    assert client.get('/graph?nodes=10000').status_code==422
    for path in ['/workflow','/knowledge','/learn','/experience','/impact','/compare','/codegen']:
        assert client.get(path).status_code==200


def test_shared_highlighter_lexical_output_preserves_text_and_escapes_html():
    import shutil
    node=shutil.which('node')
    if node is None:pytest.skip('Node is optional for source checkout; browser verification covers the viewer.')
    path=Path(__file__).resolve().parents[1]/'src/tm1_insight/api/static/syntax.js'
    script="""const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert');let ctx={window:{},document:{readyState:'loading',addEventListener(){}}};vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),ctx);let text=\"IF(1=1);DB('Cube_A',!Year,'<script>');# comment\";let out=ctx.window.tm1Highlight.rules(text);assert(out.includes('tok-kw2'));assert(out.includes('tok-kw1'));assert(!out.includes('<script>'));assert(ctx.window.tm1Source.mount);"""
    subprocess.run([node,'-e',script,str(path)],check=True,capture_output=True)


def test_source_viewer_copy_preserves_original_crlf_and_trailing_space():
    import shutil
    node=shutil.which('node')
    if node is None:pytest.skip('Node is optional; source viewer also has real browser acceptance.')
    path=Path(__file__).resolve().parents[1]/'src/tm1_insight/api/static/syntax.js'
    script=r"""
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert');
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.events={};this.className='';this.dataset={};this.textContent='';this.innerHTML='';this.classList={contains:x=>this.className.split(' ').includes(x),add:x=>this.className+=' '+x};}
 before(x){x.parentElement=this.parentElement;}
 append(x){this.children.push(x);x.parentElement=this;}
 prepend(x){this.children.unshift(x);x.parentElement=this;}
 addEventListener(type,fn){this.events[type]=fn;}
 addEventListenerOptions(type,fn){this.events[type]=fn;}
 replaceChildren(){this.children=[];this.innerHTML='';}
 insertAdjacentHTML(position,html){
   this.innerHTML+=html;
   const rows=html.match(/<div class="code-line">/g)||[];
   for(let i=0;i<rows.length;i++){const row=new Element('div');this.children.push(row);}
 }
 setAttribute(){}
 querySelectorAll(){return [];}
 querySelector(){return null;}
 getBoundingClientRect(){return {top:0,height:0};}
}
let written;
let ctx={window:{},document:{readyState:'loading',addEventListener(){},createElement:tag=>new Element(tag)},navigator:{clipboard:{async writeText(text){written=text;}}},setTimeout(){}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
let pre=new Element('pre');pre.parentElement=new Element('section');let code="  IF(1=1);  \r\nCellPutN(1,'<safe>',vYear);\r\n";
ctx.window.tm1Source.mount(pre,{code,mode:'ti',start:42});
let copy=pre.parentElement.children[0].children.find(x=>x.tag==='button');
copy.events.click().then(()=>{assert.strictEqual(written,code);assert.strictEqual(ctx.window.tm1Source.text(pre),code);assert(pre.innerHTML.includes('&lt;safe&gt;'));assert.strictEqual(copy.textContent,'已复制');}).catch(e=>{throw e;});
"""
    subprocess.run([node,'-e',script,str(path)],check=True,capture_output=True)
