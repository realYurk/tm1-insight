import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("publication_guard", Path(__file__).parents[1] / "scripts/check_publication.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def test_publication_allows_product_text_only():
    assert guard.inspect("src/tm1_insight/tasks.py", b"# product source", []) == []
    assert guard.inspect("docs/PRODUCT.md", b"# product contract", []) == []
    assert guard.inspect("AGENTS.md", b"# repository constraints", []) == []
    assert guard.inspect("PRODUCT_CONSTITUTION.md", b"# product direction", []) == []
    for name in ["data/db/model.duckdb", ".env", "exports/report.json", "docs/customer.zip", "imports/data.csv", "collections/model/raw/cubes/private.json"]:
        assert guard.inspect(name, b"private", [])


def test_publication_detects_credentials_without_exposing_values(tmp_path):
    credential = b"synthetic-test-credential"
    assert guard.inspect("src/example.py", credential, [credential]) == ["contains a local credential value"]
    (tmp_path / ".env").write_text("TM1_PASSWORD=" + credential.decode(), encoding="utf-8")
    assert guard.local_secrets(tmp_path) == [credential]
