# Cube-Centric Reverse Engineering 1.0 — audit and delivery

## 1. Product outcome and baseline (Stage A)

Local baseline was `e279270`, including Workbench 1.1. Work is isolated on `codex/cube-centric-reverse-engineering`; existing commits, screenshots and governance files are preserved. The four product layers and codegen navigation remain. No state-management, dual-pane Cube browser, Dimension table, home redesign, new AI feature or Java generator is introduced.

Baseline command (fresh temporary TM1_INSIGHT_HOME before imports):

```
.venv/Scripts/python.exe -m pytest -q
```

Result: **572 passed**, one existing Starlette/httpx deprecation warning, **76.68 s**.

Audited sources: PRODUCT_CONSTITUTION.md, AGENTS.md, AI_INSTRUCTIONS.md, README, architecture/architecture_extraction/workflow, learning/calculation and syntax/understanding, store/calculation/invocation/dimensions/schema/queries, graph_adapter, architecture routes/templates and Cube Workbench tests. Actual behavior, not historical README claims, determined the implementation.

Findings:

- `workflow.reconstruct` already uses definition nodes and explicit CellGet values. It does **not** create value lineage by joining read/write objects. Unknown functions stop value tracing.
- `dimension_comparisons` uses source × target pairs for **structural comparison only**, with UNCONFIRMED mapping. It was not a proven dimensional mapping engine. This remains explicit, with `basis=STRUCTURE_ONLY_NOT_VALUE_MAPPING`.
- VIEW source binding already supports conservative Prolog literals/aliases. Data Source Variables/field metadata are not generally captured, so Data inputs cannot be bound to a VIEW cell solely by a variable name.
- Worksheet strings were uniformly redacted, hiding even actual fixed member coordinates. Conservative exit/branch merges also lost unique unconditional Prolog constants. An undefined Data variable and a lost immutable literal were both shown as unknown, although the evidence differs.
- Complete expressions inside IF were labelled PARTIAL together with the unverified execution path. The new explanation distinguishes expression support from execution verification; legacy summary/status behavior is preserved.
- Attribute functions, arbitrary MDX/subsets, cross-TI expression substitution and runtime numerics were not supported. They remain limited.
- Architecture v2 already stops helper fan-out, preserves helper effects, separates Rule consumers and restricts Chore membership. These boundaries are reused. No Unified Model Graph full-model materialization or traversal through shared Dimension is added.
- Architecture had only a Process root. Existing Cube producers/readers and Rule indexes can seed bounded source verification.

## 2. Evidence contract (Stage B)

The additive `formation_version=cube-formation-1` projection retains the compatible `architecture-1` base and Extraction v2 sections. It distinguishes STRUCTURAL_RELATION, EXECUTION_CALL, CHORE_SCHEDULE, CUBE_READ, CUBE_WRITE, VIEW_DATASOURCE_BINDING, STATIC_VALUE_DEPENDENCY, RULE_REFERENCE, FEEDER_REFERENCE and UNRESOLVED_RELATION. Records include typed endpoints, TI/Rule context, source evidence, scope, resolution, conditions where supported, unknown reasons and runtime_verified=false.

Explicit reads have independent usage classifications: value expression input, target-coordinate lookup, control expression input or observation only. Classification follows existing definition DAGs. Opaque functions in a condition do not establish return-value dependence. A read used to select a coordinate or condition is not added to numeric value lineage. Multiple roles at one read location retain separate evidence.

Evidence retains deterministic report-local aliases and content-derived stable identities. Newly exposed fixed member values require both a source definition chain and membership in the actual recorded Dimension. Arbitrary strings, DSNs, credentials and unused constants are never published through the private resolver map.

## 3. Finite semantics (Stage C)

The existing Builder retains private literal values only during the selected-process adapter call; the map is removed before serialization. Coordinates are annotated as verified fixed member, declared parameter, numeric literal, CellGet coordinate lookup or unresolved. Actual Cube dimension order and arity determine alignment.

A fallback definition is permitted only for a unique top-level Prolog literal assignment with no competing assignment in any Section. It is registered only after visiting its source position. Conditional definitions, later reassignments and sensitive names invalidate this fallback. This recovers immutable coordinates across conservative exit merges without implementing a second parser or claiming path execution.

Every write keeps its section/line/column, overwrite/increment mode, value expression, target coordinates, conditions, source reads, unresolved inputs and evidence. Supported numeric arithmetic and safe-division syntax reuse `workflow.reconstruct`. Supported branch-local formulas can be displayed while branch reachability stays unverified. String value writes remain observed, not a fabricated numeric formula.

Coordinate correspondence is generated only for a read on the actual value-definition chain and source/target coordinates using the same supported expression. It explicitly means source-code expression equality, not business member mapping, aggregation or numeric contribution. Shared dimension names alone produce no correspondence.

VIEW binding remains separate from Data-row value binding. External source type (e.g. ODBC) can be recorded from a supported declaration while connection identifiers, SQL/field mapping and value flow remain unknown. AttrS/AttrN, unknown functions and dynamic objects preserve unsupported status.

## 4. Process/Cube architecture (Stage D)

`workflow.build` accepts optional root candidates and a root acceptance predicate; old callers retain the same default behavior. A Cube analysis selects indexed writer candidates, verifies direct write targets in source, and expands the accepted forward roots through the existing workflow engine. Rejected or missing candidates remain explicit. Source budgets apply across roots; no full TI-code scan occurs. Indexes may miss dynamic/wrapper writers, so the list is never claimed globally complete.

Core roots are source-verified producers. Helpers remain folded, with observed preparation, clear, cleanup and write effects. One-hop explicit literal helper target binding remains supported; callee coordinates/formulas are not silently substituted into a caller. A dynamically bound helper writer cannot be promoted solely from its name or an index entry. True helper write effects survive in implementation and bound write explanations.

Cube root metadata and own Rule are assembled even with no TI producer. Direct Rule/Feeder DB references remain grouped, source-backed references; complete Rule evaluation is not implemented. Reader candidates are source-verified within a separate small budget and remain external consumers; their calls and other dependencies are not expanded. Actual Caller calls and recorded Chore scheduling retain execution semantics.

Core Cube structures include actual Dimension order, counts, recorded hierarchy names and bounded target-dimension consolidation samples (first 50 edges with recorded weights and completeness/paging metadata). Elements and further weights remain available via existing paginated Dimension inspection. These are structural records, not proof of a TI aggregation operation or a complete hierarchy migration package.

The existing Architecture workspace gains Process/Cube selection and a Data Formation view. Cube details add a link to this workspace. Default write pagination filters technical/unknown-target entries on the server and can focus the selected Cube; logs do not fill pages before actual target writes. Cube, TI, original Rule and line-located evidence are linked. Workbench 1.1 state management and visuals remain intact.

## 5. Example and exports

[Complete synthetic Architecture.md](EXAMPLE_CUBE_FORMATION_1_0.md) demonstrates:

```
Cube_B[Product=pProduct,Scenario='ACT']
= Cube_A[Scenario='ACT',Product=pProduct] * 2
```

Both dimension orders are model records. ACT is a catalog-verified fixed member; pProduct is a declared parameter. The expression depends on the explicit CellGet value. It is not runtime verification. The tests also show a read of Cube_A with an unrelated constant write to Cube_B: no A→B value dependency is produced.

Existing Architecture.md/JSON, Evidence.json, Diagnostics.json and ZIP are retained. Markdown adds compact common target-coordinate contracts with independent write-site variations and condition paths; source evidence remains in machine data. Structural comparison duplicates are folded only in presentation. Formula/condition/write facts are not merged. ZIP uses fixed archive timestamps so its bytes are reproducible; archive timestamps are not model collection times. All in-scope original DAGs remain inspectable; unexpanded source is never claimed complete.

## 6. Verification and performance (Stage E)

Behavioral tests cover all requested categories: static arithmetic/value dependency, unrelated read/write, VIEW versus Data variable, helper clear/preparation/write/cleanup, branch/dynamic target, Rule versus Feeder, Caller/Chore, shared-object/index counterexamples, reversed dimension order, fixed members, privacy, source budgets, cancellation, API compatibility and exports. Existing tests were neither deleted, skipped nor weakened.

- Focused initial core regression: **45 passed**, **6.36 s**.
- New formation/calculation/architecture verification: **43 passed**, **5.63 s**.
- Final full regression: **585 passed**, **0 failed**, one existing warning, **80.33 s**. Focused export checks also passed (**28 passed**, **6.22 s**).
- JavaScript syntax check: `node --check src/tm1_insight/api/static/architecture.js` passed.
- Synthetic scale: 3,004 TI, 3,004 Cube, 10,005 Dimension names. Only **2 distinct TI bodies** loaded; **0.272 s**, **4.96 MiB Python tracemalloc peak**. Native DuckDB memory is excluded; this is a local spot-check, not a general SLA.
- Requested local Process and Cube existed. Before/after reports and machine exports are private, outside Git. Analysis opened DuckDB read-only, never executed TI, and compared DB/WAL hashes. The real source supports improved target coordinates and lookup/control roles, but a complete Data input-to-value calculation was **not** newly proved. The final report gives the exact private comparison.

## 7. Files and compatibility

- learning/calculation.py: finite immutable literals, private constants, control/coordinate read nodes; parser version 7.
- store/calculation.py: catalog validation and coordinate annotations.
- workflow.py: optional multiple source roots and acceptance; additive expression status.
- architecture.py: Cube seed/verification, shared boundaries, model metadata, result indexing; engine revision 8.
- formation.py: typed relationship and write-explanation projection, external consumer verification, compact write export.
- architecture_extraction.py: role-labelled reads, target coordinate contracts and structural presentation.
- api/architecture.py: additive Cube request fields and filtered write paging.
- api/static/architecture.js, templates/architecture.html, templates/_cube_detail.html: existing workspace integration.
- tests/test_cube_formation.py, README and delivery/example documentation.

No DuckDB schema migration, new dependency, new cloud service or CLI change. Source jobs reuse existing progress, cancellation, worker/cache and evidence/export mechanisms. Packaging imports remain static and covered by existing Portable tests. Existing Portable binaries were not overwritten or rebuilt; this delivers the source application and running local service.

## 8. Limitations and stop point

Still missing for Java equivalence: captured Data Source Variables/column bindings, actual View/Subset/MDX membership, general attribute mapping, cross-process parameter/default substitution, opaque function effects, full Rule/Feeder evaluation and precedence, complete hierarchy/consolidation semantics, runtime order/iteration counts and numeric oracle datasets. Strings not verified against a Dimension catalog remain hidden/unresolved. Writer/read indexes can be incomplete. All budgets and unverified boundary candidates remain explicit.

The next high-value slice is collecting and validating Data Source Variables/field metadata and tying one recorded VIEW row to a write value. It is a recommendation only. This task stops after delivery; no Java conversion phase begins.
