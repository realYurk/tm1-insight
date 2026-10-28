import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_rule_slice_only_displays_target_and_source_link():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for the presentation test')
    source = Path('src/tm1_insight/api/static/rule-slice.js').read_text(encoding='utf-8-sig')
    script = '''
const assert=require('node:assert/strict');
class E {constructor(){this.children=[];this.textContent='';} append(x){this.children.push(x);}}
global.window={};global.document={createElement:()=>new E()};
eval(SOURCE);
const card=window.TM1RuleSlice.render({target:"['Amount']",href:'/explorer/cube/B#rules',expression:'SECRET LONG FORMULA'});
const text=card.children.map(c=>c.textContent).join(' ');
assert.ok(text.includes("['Amount']"));assert.ok(!text.includes('SECRET'));assert.equal(card.children[2].href,'/explorer/cube/B#rules');
'''.replace('SOURCE', json.dumps(source))
    subprocess.run([node], input=script, text=True, capture_output=True, encoding='utf-8', check=True)
