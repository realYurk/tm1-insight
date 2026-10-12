import hashlib
import json
import pytest
from test_datasource import _make_real_db
from tm1_insight.config import Settings
from tm1_insight.learning.inventory import study_directory


def test_directory_keeps_independent_models_and_sources_unchanged(tmp_path):
    root=tmp_path/'input'
    databases=[_make_real_db(root/name) for name in ('one','two')]
    hashes=[hashlib.sha256(path.read_bytes()).hexdigest() for path in databases]
    result=study_directory(Settings(),root,tmp_path/'reports')
    assert len(result['models'])==2
    assert result['files']==2
    for model in result['models']:
        assert model['summary']['processes']==1
        assert (tmp_path/'reports'/model['report']).exists()
    assert hashes==[hashlib.sha256(path.read_bytes()).hexdigest() for path in databases]
    ledger=(tmp_path/'reports'/'files_manifest.jsonl').read_text().splitlines()
    assert all(not json.loads(line)['content_verified'] for line in ledger)


def test_directory_rejects_output_inside_original(tmp_path):
    with pytest.raises(ValueError):study_directory(Settings(),tmp_path,tmp_path/'output')
