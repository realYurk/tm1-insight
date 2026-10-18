# Unified calculation relationships and workflow specification v1

Tasks 22–25 project existing local evidence into a usable Cube-centric workflow.
No new parser, execution engine, graph traversal or integrated AI service.

## Existing implementation inventory (before development)

|Relationship|Existing source / store|Evidence|Limit|
|---|---|---|---|
|Process calls Process|`process_calls_process` candidate index; `store/calculation.inspect`, `workflow.build`, Architecture execution relationships|Section, line/column, source hash, actual call, parameter bindings, conditions|Index alone is not confirmed; dynamic calls and expansion budgets remain explicit|
|Chore schedules Process|`chore_runs_process`, Architecture bounded schedule queries|Chore, target Process, recorded step order, table provenance|Not proof of enablement or execution; limited to core TI / verified callers|
|Process reads/writes Cube|`process_reads_cube` / `process_writes_cube` discovery; worksheet observations; Formation|Source operation/location/hash and helper binding evidence|Co-reading and co-writing do not prove value transmission|
|Write coordinates/value chain|Calculation worksheet, `write_explanations`, Data Row Binding|Write point, coordinate bindings/member evidence, IF context, definitions, read nodes|Variables/VIEW mapping can be missing; caller-bound helper coordinates are not substituted|
|Rule owner/LHS/RHS|`cubes.rules`, `rule_semantics`, `rhs.expression_ir`|Original offsets, source hash, conservative LHS, function/branch/DB nodes|Static structure is not complete semantics or runtime proof|
|Rule DB references|`rule_references_cube` candidate index; verified Rule IR|DB call position, Cube catalog resolution, dynamic coordinate reasons|Known Cube identity is not a confirmed coordinate or complete formula|
|Feeder|Independent `feeder_semantics` in the same Cube Rule source|Source/target area, DB occurrences, source position|No proven association to one numerical Rule; multi-target UNKNOWN stays UNKNOWN|
|Cube dimensions|`cube_has_dimension`|Actual dimension name and zero-based order|Structure is not value dependency|
|Indirect reachability / impact|`lineage.engine`, `impact.engine`, existing module `relation_path`, Workflow cycles|Existing direct dependencies / paths|Projection reuses bounded module paths and cycles; no second closure algorithm|

`domain.model.Reference` is a syntax observation; `Dependency` expresses a legacy
depends-on direction and numeric confidence. Existing Formation dictionaries are
closer to this workflow, but do not give each Rule/Feeder statement its own identity
or unify evidence/reference conventions. The new contract is an additive dictionary
projection over these existing public report objects. Legacy dataclasses, tables,
directions, parsers and APIs are unchanged.

## Contract: calculation-relations-1

Architecture adds `relation_objects`, `unified_relations`, `relation_evidence`,
`unified_model`, `business_steps`, `rule_summaries`, `workflow_spec`.

Object identity is a SHA256 of canonical type/name/owner/location. Named model
objects are scoped to the report's model fingerprint; Rule/Feeder identities include
owner Cube, source hash and source lines. Identities are deterministic, not UUIDs,
timestamps or probabilities. A changed Rule source deliberately changes statement identity.

Each relation contains stable `id`, `source`, `target`, `source_type`, `target_type`,
display names, `relation_kind`, `mechanism`, `direction=SOURCE_TO_TARGET`, `owner`,
`directness`, categorical `status`, `semantic_status`, `evidence` IDs,
`context_refs` (JSON pointers in companion Architecture.json), `unresolved_reasons`,
`runtime_verified=false`, and a site/order/path qualifier when applicable.
Indirect reachability also has ordered `path_relation_ids` referring to the existing
direct call relations. Only already computed module paths are projected, not an
all-pairs closure. Technical/helper effects stay inspectable; `detail_only` controls
default presentation, independently of fact certainty.

Relations aggregate identical semantic keys and deterministically union evidence.
Different kind, mechanism, owner, status, semantics or write-site qualifier cannot
merge. Conditions, parameters and coordinates remain in the referenced resources,
so multiple call/write sites retain independent contexts. Missing evidence forces
UNKNOWN. Evidence registry stores only whitelisted source/table locations and hashes,
never full code or connection settings.

|Kind|Direction and meaning|
|---|---|
|PROCESS_CALL|caller → callee; direct source invocation|
|EXECUTION_REACHABILITY|root → descendant; existing indirect bounded path, not execution order|
|CHORE_SCHEDULE|Chore → Process; offline schedule definition|
|CUBE_READ / VIEW_DATASOURCE|Cube → Process; observed read / source binding|
|CUBE_WRITE / TI_WRITE_SLICE|Process → Cube; write observation / separately referenced write site|
|CANDIDATE_FORMATION|source Cube → target Cube, owned by TI; co-observed access only|
|STATIC_VALUE_DEPENDENCY|source Cube → target Cube; confidence comes unchanged from supported worksheet dependency|
|RULE_DB_REFERENCE|referenced Cube → Rule statement; Cube identity confirmation only|
|RULE_TARGET|Rule statement → owner/target Cube; LHS/RHS semantics separate|
|FEEDER_OWNER|Feeder → owner Cube; ownership only|
|FEEDER_DB_REFERENCE|Feeder → referenced Cube; no numerical calculation or forced single target|
|CUBE_DIMENSION|Cube → Dimension; qualifier retains actual order|
|UNRESOLVED_DEPENDENCY|observed owner → explicitly unresolved object; never confirmed|

Statuses are SOURCE_CONFIRMED (the named fact only), STATIC_DEPENDENCY_CONFIRMED
(supported static dependency only), CANDIDATE, PARTIAL, UNKNOWN. Rule/coordinate
semantic status is retained independently; no inferred runtime probability.
Feeder `rule_association=OWNER_CUBE_ONLY` explicitly avoids invented Rule matching.

## Product workflow

Open **Cube → search → overview → 解析数据形成**. The existing Architecture workspace
shows current source type, availability, model fingerprint, counts, software version
and Architecture revision. Existing safe source selection remains under Settings.
No automatic source switch or server connection is introduced.

Overview now includes CORE processing rows: observed primary inputs, overwrite vs
increment counts, common target slices, row-metadata gaps and write evidence links.
Primary inputs are VIEW bindings or existing value-expression reads; control/coordinate
lookups remain in details. Purpose is human-confirmation-required, not inferred from
Cube names. Helpers are folded using existing module classification and source effects.
Steps are an explanatory organization, never an execution sequence.

**关系与计算** groups data, execution, Rule, Feeder and structure. The default list is
server-filtered and paginated before display. Unknown targets, technical helpers and
control/coordinate-only reads are in details. Rule/write contexts load on demand;
Overview requests `rule_summaries`, not complete Rule ASTs. Existing `view=rules`
retains its original full payload for compatible consumers.

## API and export

Existing task create/status/cancel/result/export remain. Added result sections use
the existing SQLite artifact index, with searchable source/target/type names.

* `result?view=unified_relations&relation_group=data|execution|rule|feeder|structure`
* `relation-fact?id=u<sha256>` retrieves one compact proof.
* `relation-context?ref=/rules/I/rule_semantics/J` (or feeder_semantics / write_explanations)
  retrieves one existing calculation resource; pointers are restricted and bounds checked.
* `export?format=relations` streams UnifiedRelations.json from the existing index.

ZIP adds UnifiedRelations.json alongside the existing Architecture.json / .md,
Evidence.json and Diagnostics.json. Compact JSON has objects/relations/evidence,
statistics, business_steps and workflow_spec. Its context_document is Architecture.json:
keep both files or use ZIP. Trees and source are stored in the existing resource
once, not repeated on every relationship. Legacy export fields remain available.
Markdown summarizes relation types with representative source locations, while full
per-statement identities and evidence stay in JSON. Existing per-write coordinate
contracts, conditions, definitions and risk notes remain in the human report.

Architecture revision 14 invalidates derived task-cache keys; original collection
schema and snapshots are unchanged. Existing artifacts without additive fields
remain readable. Projection has a 30,000-relation budget, reports truncation, and
uses existing progress callbacks so cancellation propagates.

## Acceptance and boundaries

Synthetic tests cover direction, semantic identity, deterministic union/sorting,
multiple proofs, direct/indirect calls, cycles, unknown coordinates and Cube names,
independent/multi-target Feeders, old snapshots, compact exports, source contexts,
pagination and helper folding. Real local acceptance uses Allocation Driver BP.
The private sprint report records exact test counts, real evidence, browser results,
timings, file sizes, Portable build checks and DB/WAL hashes. Corporate source and
private analysis artifacts are not included in the repository or Portable bundle.

Data Row variables, attribute-returned coordinates, LHS ownership and some Feeder
targets remain unresolved. A missing schedule in a bounded scope does not prove
no server schedule exists. Business purpose and runtime transfer/equivalence are
not confirmed by this static specification. No Java implementation is generated.
