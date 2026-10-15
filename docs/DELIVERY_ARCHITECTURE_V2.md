# Architecture Extraction v2 — delivery

## Outcome and audited root causes

The four-layer product architecture is unchanged. This slice improves bounded module extraction and readable architecture, retaining offline source evidence. No new page, AI integration, code generation template or live TM1 operation was introduced.

The old `architecture.build` calls the bounded **forward-only** `workflow.build`; it does not invoke `graph_adapter.dependencies_from_store` or traverse a unified undirected graph. Inspection found these actual expansion paths:

1. Rule owners were expanded with `rule_references_cube WHERE source_cube IN (all observed cubes)`. Each candidate owner's entire DB-reference list was included if any reference touched the selected set. Shared configuration/helper Cube references could therefore bring many unrelated Rule references into presentation. This was a bounded reverse Rule lookup, not proven infinite traversal.
2. `chore_runs_process` was queried using every parsed TI, including shared helpers. A maintenance Chore scheduling the same helper could appear without scheduling the entry or a business descendant. A new synthetic regression reproduces precisely this path.
3. Forward workflow recursion expanded helper internal calls. There was no reverse TI-consumer expansion, nor a traversal through shared dimensions; do not attribute the issue to those mechanisms.
4. Markdown emitted every effect, Rule reference, dimension JSON, relationship, evidence and unresolved record. HTML escaping of JSON made the default document a machine dump.
5. VIEW binding accepted only direct string literals, and rejected a whole TI if any control block existed. An independent conditional log block could hide an otherwise simple source binding.

The current available local model did **not** reproduce the user-reported several-thousand Rule references or maintenance Chore. The exact previously exported report/database revision was not available as an input artifact. Claims about that historical export remain unverified; the identified code paths are independently tested.

## Scope resolver and classification

`Boundary` is a small expansion policy over existing workflow parsing, not another graph engine. Source invocation is the only TI expansion relation. Entry and business callees form CORE by forward evidence-backed reachability. Direct system-namespace helpers are inspected for real effects and assigned TECHNICAL_SUPPORT; their internal calls stay as boundary observations unless explicitly enabled. Names never establish a clear/copy/financial effect. Business processes reached only through an expanded helper do not become CORE.

Cube roles come from source reads/writes/data-source bindings and explicit logging/system evidence; mere name prefixes such as Info/Sys do not decide business meaning. Namespace/logging objects default to technical support. Other reference-only cubes and shared dimensions are EXTERNAL_DEPENDENCY. Configuration reads, control/value diagnostics and source DAGs remain in JSON even when folded from prose.

Core read/write Cube Rule source is eligible for parsing. External Rule consumers are separate DOWNSTREAM_CONSUMERS index candidates. `include_downstream` permits bounded source verification without promoting consumers to CORE. No Rule-consumer transitive walk occurs. Chores attach only to nontechnical forward TI scope or source-verified callers of the entry. Recorded schedules do not prove enabled/running status.

Supported scope controls: `max_depth`, `max_processes`, `max_nodes`, `allowed_relationship_types`, `include_downstream`, `include_technical_details`. Relationship filters control expansion, not deletion of already observed source facts. `max_nodes` budgets expanded TI (including verified callers), Cube, Dimension and extra Rule source; retained boundary references and recorded schedule rows are separately bounded. Existing character/node/evidence budgets remain. Budget diagnostics retain omissions rather than presenting completeness.

## Transformation and structure

One source-backed summary per core Process includes source/target cubes, read/write observations, grouped preparation, source binding, individual calculation/write contexts, coordinates, evidence and partial resolution. Preparation groups retain target and conditions. Each write keeps its own formula, section/line, conditions and coordinate nodes; different branches or unknown formulas are never merged into a confirmed operation. Helper read/write/clear effects survive folding. Numeric value dependency still comes only from the existing calculation DAG, never a read/write join.

VIEW source extraction reuses `structure` and tokenized assignments. It supports unique top-level literal/alias definitions and a final unconditional VIEW type assignment overriding earlier NULL guards. The result is explicitly conditional on reaching that assignment; early exits/actual execution are not proved. Conflicting or conditional source aliases remain unknown. Dynamically constructed view names/member selections are not evaluated.

Core cubes retain full recorded dimension order and completeness. Pairwise structural comparisons show shared/source-only/target-only dimensions. They do not imply member identity, same grain, aggregation, a measure role or a value flow. Supported coordinate nodes and their definitions remain in the selected TI DAG; arbitrary attribute lookup and cross-TI parameter substitution are not added.

## Exports and evidence

The default Markdown contains only the requested six sections: module overview, models, processing, execution/scheduling, grouped Rule/Feeder, boundary/migration concerns. Rule counts are computed from actual parsed reference records. Feeder references are labelled separately and never described as producing values. Technical helper parameter dumps, parser diagnostics, hashes and flattened evidence are omitted from this document, not from the machine export.

Existing JSON/Markdown endpoints remain. ZIP adds Architecture.md, Architecture.json, Evidence.json and Diagnostics.json. ZIP is disk-spooled, evidence is streamed from the existing result index, and pages do not decode the whole report. Architecture JSON retains all in-scope facts and implementation DAGs. Diagnostics retain original workflow unknown records plus architecture scope issues. Out-of-scope source is not claimed to be fully collected.

Within identical source/scope, exports and numeric `eN` references are deterministic. Deduplicated evidence also carries a full content-derived `stable_id`, including source hash for code locations, for matching across different report scopes. Numeric `eN` aliases are local to one report; do not compare them across scope changes. Conclusions point to these records through summary/group/relationship evidence references.

The compatible base schema stays `architecture-1`; `extraction_version=architecture-extraction-2` and engine revision 5 invalidate old task artifacts. Legacy CLI, workflow and codegen entry points remain.

## Files

- `architecture.py`: bounded assembly, source binding, core Rule selection, schedule restriction, evidence identity, v2 projection.
- `architecture_extraction.py`: boundary policy, summaries, structural comparison, six-section Markdown, streamed evidence/ZIP.
- `workflow.py`: optional expansion callback; original default behavior preserved.
- `api/architecture.py`: scope validation, cache key, compatible exports plus bundle/evidence/diagnostics.
- `api/static/architecture.js`, `api/templates/architecture.html`: existing workspace scope controls, grouped rules, source binding, dimension differences, bundle download; corrected the existing TI suggestion URL and invalidated stale search responses when analysis starts; no new page or palette redesign.
- `tests/test_architecture.py`: behavioral regressions and export consistency.
- README and delivery/example documentation.

## Verification

All pytest runs set a fresh temporary TM1_INSIGHT_HOME before importing application settings; real model tests open DuckDB read-only.

- Baseline: `python -m pytest -q`: **497 passed**, one existing Starlette/httpx deprecation warning, **64.56 s**.
- Focused workflow/architecture verification: **29 passed**, **5.86 s** (before final additional test).
- Complete regression: **503 passed**, one existing warning, **63.30 s**; additional export assertions: **15 passed**, **4.13 s**.
- `node --check src/tm1_insight/api/static/architecture.js` passed.
- Tests cover shared-helper maintenance exclusion, optional consumer expansion, 600 repeated Rule references plus separate Feeder evidence, aliases/NULL guards/conflicting sources, write-branch separation, no invented value join, node/type limits, cancellation, pagination, source changes, byte-identical repeat exports, codegen compatibility, read-only DB hash and ZIP/JSON evidence consistency.
- Synthetic scale spot-check: 3,004 TI names, only 3 forward TI source reports parsed, **0.336 s**, **3.22 MiB Python tracemalloc peak**. Native DuckDB allocations are not included; this is a local spot-check, not a universal SLA.
- Local requested ACT existed. The complete private report now separates VIEW source, explicit reads and writes, and includes core Cube dimensions. Before/after exports and numerical measurements are delivered privately outside the repository. DB and WAL hashes were unchanged. No real source or business exports are committed.

Full public synthetic example: [EXAMPLE_ARCHITECTURE_V2.md](EXAMPLE_ARCHITECTURE_V2.md). The user receives the complete private real Architecture.md and ZIP as local links.

## Limitations and stop boundary

This is static reconstruction. Actual source-row variable binding, dynamic View/Subset membership, general attribute mappings, helper parameter aliases/multiple-hop substitutions, full Rule/Feeder evaluation, runtime order and numerical Java equivalence remain unresolved. Clear effects with dynamic targets remain explicit unknowns. Optional helper expansion may cost more and is budgeted. Hierarchy/member packages are still lazy rather than embedded wholesale in the export. Portable binaries were not rebuilt; this delivers source and the local running application.

No next-phase work is started. A subsequent explicit task can extend source-row/coordinate semantics using the retained evidence.
