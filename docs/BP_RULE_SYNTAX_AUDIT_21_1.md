# Task 21.1 — Core BP Rule syntax audit

## Decision before implementation

No production parser change is justified by this scoped audit. This is an audit
and regression-protection delivery, **not a semantic capability improvement**.

Read-only inspection of the three requested local Cube Rule sources found 71
numeric/string Rules, all with `expression_ir.structure_status=PARSED`. No unknown
syntax node or exponentiation expression was observed in their Rule RHS trees.
This does not establish complete computation semantics: area member ownership,
attribute values, hierarchy predicates and dynamically calculated coordinates
remain unconfirmed.

The labelled DB coordinate syntax occurs twice, both in one multi-target Feeder
in the PnL source (Feeder starts at line 795; calls at 797 and 798). It does not
occur in the 71 numeric/string Rule expressions. The Feeder remains UNKNOWN;
neither its multiple targets nor its coordinate labels should be reinterpreted as
a numerical calculation. Expanding that path would be a separate Feeder task.

Core Rule examples at PnL lines 70, 182, 354, 368 and 384 already retain attribute
function arguments, concatenation, DB identity and source spans. Their resulting
coordinate values remain UNKNOWN. Syntax recognition cannot establish the result
of an attribute lookup or resolve area membership without additional validated
metadata. Reducing these UNKNOWNs by parser relaxation would introduce unsupported
certainty.

## Scope and evidence

Model Foundation / Lineage & Relationships: determine whether a missing syntax
structure blocks calculation explanation before changing the parser.

Only local `cubes.rules`, Cube names and `cube_has_dimension` metadata were queried
through a read-only DuckDB connection. No cells, Process execution, server access,
network diagnostics, schema migration or formal store writes. Existing uncommitted
work and Task 20/20.1/21 source are retained.

The private local Task 21.1 report contains every Rule's Cube, line, original
expression, current tree, reasons, interpretation impact, and the two actual
labelled Feeder calls. Corporate source is not copied into the repository.

## Changes and verification

Only this document and `tests/test_bp_rule_syntax_audit.py` are added. Six synthetic
regression cases protect the observed attribute-generated coordinate and string
concatenation structures, unknown identifiers, the multi-target labelled Feeder
boundary and unsupported numeric syntax. They do not contain enterprise fixtures.
No production schema/API/cache revision changes. Source hashes and complete parsed
results before/after are equal; therefore no node is claimed to improve its status.

Focused suite: 102 passed, 0 failed, 0 skipped, one existing Starlette/httpx warning.
The private report records final full-suite output and data/code hash verification.

Five-run median build times for the three scoped sources: approximately 3.835 ms,
55.868 ms and 0.704 ms respectively (local machine; not a runtime TM1 benchmark).
Compact UTF-8 JSON sizes before and after are identical: 125,148 / 1,979,928 /
18,234 bytes. The existing PnL result is about 1.89 MiB; no serialization redesign
was performed. Build measurement excludes database loading; serialization is
measured separately in the private artifact.

## Remaining work

No real Rule was found that this iteration could legitimately move from unknown
syntax to confirmed syntax. The requested before/after semantic improvement gate
is therefore **not met**, and no improvement is claimed. A future separately
scoped task could investigate multi-target Feeder labels, or validate the local
metadata needed for attribute-generated coordinates. Neither is implemented here.
