import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_shared_write_card_renders_fixed_dynamic_and_omits_unknown():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for frontend component checks')
    source = Path('src/tm1_insight/api/static/write-point-card.js').read_text(encoding='utf-8-sig')
    harness = r'''
const assert = require('node:assert/strict');
class Element {
  constructor(tag) {this.tag=tag; this.children=[]; this.textContent=''; this.className='';}
  append(...items) {this.children.push(...items);}
}
global.window={}; global.document={createElement:tag=>new Element(tag)};
eval(SOURCE);
const card=window.TM1WritePointCard.writePoint({operation:'累加数值', summary:'Measure = Sales', conditions:['pYear > 0'], coordinates:[
 {dimension:'Measure', value:'Sales', kind:'FIXED'},
 {dimension:'Year', value:'pYear', expression:'pYear', kind:'DYNAMIC'},
 {dimension:null, value:'Mystery', kind:'UNKNOWN'}
]});
function text(n) {return [n.textContent,...n.children.flatMap(c=>text(c))];}
const content=text(card).join(' ');
assert.equal(card.className,'wp-item'); assert.equal(card.children[0].className,'wp-summary');
for (const term of ['累加数值','Measure','Sales','固定筛选','Year','pYear','动态表达式','pYear > 0']) assert.ok(content.includes(term),term);
assert.ok(!content.includes('Mystery'));
console.log('shared write card verified');
'''
    result = subprocess.run([node], input=harness.replace('SOURCE', json.dumps(source)), text=True, capture_output=True, encoding='utf-8', check=True)
    assert 'verified' in result.stdout


def test_both_lineage_views_use_the_shared_cube_style_card():
    root = Path('src/tm1_insight/api')
    template = (root / 'templates/cube_lineage.html').read_text(encoding='utf-8')
    assert template.index('write-point-card.js') < template.index('cube-lineage.js')
    for filename in ('cube-lineage.js', 'formation-answer.js'):
        assert 'TM1WritePointCard.writePoint' in (root / 'static' / filename).read_text(encoding='utf-8')
