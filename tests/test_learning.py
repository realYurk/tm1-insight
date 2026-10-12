import json
from pathlib import Path

from tm1_insight.learning.syntax import signals
from tm1_insight.learning.engine import build_report, markdown
from tm1_insight.learning.catalog import CATALOG, template
from test_knowledge import _catalog


def test_learning_formula_chain_preserves_position_and_hides_literals():
    result = signals(("", "", "# fake a*b/c\nnRatio = vWeight \\ pTotal;\nCellIncrementN(pAmount*nRatio, 'PrivateCube', 'X');", ""))
    assert result["proportional_writes"][0]["line"] == 3
    assert result["formulas"][0]["line"] == 2
    assert "PrivateCube" not in json.dumps(result)
    assert "nratio" == result["formulas"][0]["variable"]


def test_learning_does_not_invent_proportion_from_strings_or_ambiguous_definitions():
    assert not signals(("", "", "s='CellIncrementN(a*b/c)'; # a*b/c", ""))["proportional_writes"]
    code="nRatio=a/b; nRatio=1; CellIncrementN(pAmount*nRatio,'X','Y');"
    assert not signals(("", "", code, ""))["proportional_writes"]


def test_learning_filters_known_logging_regions_and_debug_outputs():
    code="#Region - Initialize Logging\nAttrS('Clients','X','Alias');\n#EndRegion - Initialize Logging\nAttrS('Product','A','Target');\nASCIIOutput(sDebugFile, 'abc');"
    result=signals((code,"","",""))
    assert result["operations"]["attrs"][0]["line"] == 4
    assert len(result["operations"]["attrs"]) == 1
    assert "asciioutput" not in result["operations"]


def test_report_links_facts_to_learning_cards_and_discloses_limits():
    con=_catalog()
    try:
        con.execute("UPDATE processes SET data=?",["nRatio=vWeight/pTotal; CellIncrementN(pAmount*nRatio, 'BP Output');"])
        events=[]
        report=build_report(con,"BP",lambda **event:events.append(event))
        assert report["summary"]["processes"] == 1
        assert report["processes"][0]["reads"] == ["BP Input"]
        assert "proportion" in report["processes"][0]["patterns"]
        assert report["findings"][0]["status"] == "review_required"
        assert not report["privacy"]["publishing_authorized"]
        assert "输入到输出" in markdown(report)
        assert events[-1]["stage_index"] == 5
        assert all(a["stage_index"]<=b["stage_index"] for a,b in zip(events,events[1:]))
        assert build_report(con,"NotFound")["summary"]["processes"] == 0
    finally:con.close()


def test_every_template_is_disabled_and_has_checks():
    for card in CATALOG:
        result=template(card["id"])
        assert "nEnableExample = 0" in result["prolog"]
        assert "ProcessQuit" in result["prolog"]
        assert result["checks"]
        assert not result["contains_customer_source"]


def test_launcher_has_one_browser_open_owner():
    root=Path(__file__).parents[1]
    batch=(root/"start.bat").read_text(encoding="utf-8-sig")
    assert 'start "" http' not in batch
    assert "-m tm1_insight.cli web" in batch
