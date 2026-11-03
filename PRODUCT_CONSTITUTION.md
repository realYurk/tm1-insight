# TM1 Insight — Product Constitution

> Status: binding product direction. Applies to every feature, refactor, release and AI coding session.

## North Star

**TM1 Insight is a TM1 Business Logic Reverse Engineering & Modernization Platform.**

Turn complex IBM Planning Analytics / TM1 models into **explainable workflows, evidence-backed calculation semantics, verifiable migration specifications, and reusable engineering assets**.

**Understand → Prove → Modernize → Evolve.**

Our customer problem is not “how to browse more TM1 objects.” It is: **a critical legacy calculation system runs, but nobody can reliably explain, change, or migrate its behavior.**

## Core customer jobs

1. Starting from a process, chore, cube, rule, or output cell, determine what is upstream, what executes, what transforms data, and what is still unknown.
2. Extract a **bounded functional module** from a huge TM1 model, including entry points, dependencies, inputs, outputs, execution order, formulas, dimension mappings, assumptions, and evidence.
3. Explain how a result was produced without inventing relationships or business meanings.
4. Turn a verified module into language-neutral **Calculation IR** and a migration specification for Java/SQL/other platforms.
5. Verify equivalence using fixtures, golden datasets, comparisons and recorded evidence; never claim equivalence from static analysis alone.
6. Preserve validated patterns as reusable engineering assets, not generic prose or unsupported labels.

## Product pillars — ordered

1. **Reverse Engineer**: TI/Rule/Chore/Dimension/Cube semantics, execution graph, data flow, provenance, workflow reconstruction, bounded module extraction.
2. **Prove**: source-linked evidence, explicit unknowns, confidence states, reproducible tests, numerical reconciliation.
3. **Modernize**: language-neutral calculation IR, migration contracts, architecture boundaries, target implementation guidance and equivalence tests.
4. **Govern**: snapshot compare, impact analysis, broken references, complexity, change safety.
5. **Reuse**: a library of *human-confirmed, evidence-backed, tested* calculation patterns and module templates.

Do not reverse this order. Knowledge/experience/learning features are **downstream artifacts**, not substitutes for semantic reconstruction.

## Evidence and honesty contract

Separate:
- **Observed fact**: a source-supported code/model fact with source location and parser rule.
- **Static inference**: derived relationship with explicit assumptions and limits.
- **Runtime verified**: backed by recorded execution/result evidence.
- **Business interpretation**: requires user/domain-expert confirmation.
- **UNKNOWN / PARTIAL**: dynamic or unsupported semantics; preserve unresolved expressions and reasons.

Never present a dependency edge as a proven value flow, an invocation edge as data flow, or a static fact as runtime verification. Never infer financial/business purpose solely from object names. Every claimed edge, formula and mapping must link to evidence (object, section, location, expression and snapshot where available).

## Binding four-layer product architecture

### 1. Model Foundation — 模型资产

Cube, Dimension, Hierarchy, Element, Rule, Feeder, TI Process, Chore and external file/database sources form the actual model, not a file inventory. Preserve Cube dimension order and cell grain; recorded hierarchies, elements, attributes, consolidation weights, rules/feeders, readers/writers and schedules. Missing metadata remains missing. Large dimensions require pagination or lazy loading. Every higher-layer claim must be grounded in this foundation.

### 2. Lineage & Relationships — 关系与血缘

Keep distinct structural relations, read/write references, execution invocations, source-backed static value dependencies, runtime-confirmed value flow and other static inferences. Include Cube transformations, TI calls, Chore schedules, Rule dependencies, Cube dimensions, external source bindings and configuration/data dependencies with their own evidence and limitations. Co-reading and co-writing never establishes value flow. Default summaries explain relationships rather than listing parser events.

### 3. Architecture Explorer — 系统架构探索器

This is the central user-facing product capability. Starting from a Cube, TI, Chore, prefix or keyword, discover a bounded candidate module and expand by evidence; a prefix is a discovery filter, never a reason to exclude an actual dependency. Implement supported entry types incrementally and state unavailable types explicitly.

Organize **data objects → processing steps → result objects**, with key Cube structures, inputs, intermediates, outputs, processes/rules, scheduling/call entry points, parameters, conditions, mappings, supported calculations, external interfaces and migration boundaries. Phases are an explanatory organization, not invented execution order. Preserve cycles and repeated call sites. Do not flatten a large model into an unreadable canvas.

Fold technical helpers into their owning steps using actual implementation and parameter evidence. CLEAR/ZEROOUT, VIEW_PREPARATION, SUBSET_PREPARATION, COPY/TRANSFER, DATA_TRANSFORMATION, DIMENSION_MAINTENANCE, LOGGING, CLEANUP and OTHER are operation categories, not inferred business meanings. Bedrock names alone do not establish effects. Preparation/cleanup does not prove transfer; core copying/calculation effects must survive folding. All underlying calls remain inspectable.

Default views show useful inputs, processing and outputs; parser statuses, hashes, log fields and helper calls belong in expandable implementation/diagnostics. Explain unresolved facts in concrete language; never show a meaningless UNKNOWN formula as business output. Cube Profiles retain actual dimension order, grain, hierarchy/consolidation, Rule/Feeder boundaries, mappings, clear/overwrite/increment effects, sparsity/zero/null risks. Never automatically equate one Cube with one relational table.

Architecture exports use a versioned deterministic schema containing module, entry_points, cubes, dimensions, processes, rules, chores, execution_relationships, data_relationships, transformation_steps, input_outputs, evidence, unresolved_dependencies and migration_notes. Preserve technical evidence separately from the default presentation. Navigation is workspace, asset map, the three object entries (cube, TI, chore) and a settings group; code generation and legacy tools live behind object context — see「资产提炼优先」below for the binding rule.

### 4. Business Interpretation — 业务解释

Defer large-scale development. Users may later attach business names, purposes, calculation conventions, human-confirmed rules and validated module knowledge to reconstructed architecture. These annotations must remain distinguishable from source facts. Export structured architecture for user-controlled external analysis if requested. **Do not integrate LLM, RAG, vector databases, AI agents or external AI services into the product.**

## Architecture boundaries

TM1 Server / offline exports → Collector / Existing Store → Immutable Snapshot → Parser & Symbol Resolver → Execution and Data-Flow Semantics → Calculation IR → Workflow / Module Reconstruction → Migration Specification → Equivalence Evidence.

Keep distinct concepts: Reference, Dependency, ExecutionEdge, DataFlowEdge, Lineage, CalculationExpression, ParameterBinding, DimensionMapping, Evidence, UnresolvedItem.

Prefer incremental improvements to the existing Python/Web/CLI/DuckDB/Parquet/Snapshot engines. Preserve APIs and backwards compatibility; add versioned schemas and migrations when needed. Do not rewrite working subsystems merely to conform to an idealized diagram.

## First-class workflows

### Explain a workflow
Input: Process / Chore / Cube. Output: separate execution graph and data transformation graph, step sequence, inputs/outputs, formulas supported by evidence, mappings, parameters, unresolved items, JSON and Markdown export.

### Extract a module from a huge model
Input: selected output cube/measure or process and scope boundaries. Output: dependency-closed candidate module, required external interfaces, explicit unresolved dynamic references, optional/conditional dependencies, execution ordering, source provenance, portability risks, reproducible export. Do not silently pull in the entire model or imply completeness when unknown references remain.

### Explain a number
Input: snapshot + fully specified cube coordinates + (when necessary) execution/run evidence. Output: the strongest justified explanation, clearly separating structural possibility, calculation semantics, and proven runtime contribution.

### Migrate and prove
Input: reviewed module and IR. Output: target-neutral contract, Java/SQL guidance, fixtures, test oracle, reconciliation results and unresolved semantic risks (e.g. consolidation, rules/feeders, sparsity, zero-out, overwrite, ordering, security).

## Prioritization rule

For each proposal, answer:
1. Which of **source → transformation → result → verification → migration** does this improve?
2. What observable customer task becomes faster or safer?
3. What original evidence supports the output?
4. How are partial and unknown cases shown?
5. Can the change be tested on synthetic fixtures and a large offline model without mutating business data?
6. Does it move us toward a sellable, standalone professional tool?

If these cannot be answered, defer or reject the feature.

## Non-negotiables

- **Deterministic, explainable core; no integrated LLM, RAG, AI agents, vector database or external AI service.** Users may export structured context themselves; external interpretation never replaces source truth.
- **Software/data separation**: Portable binaries contain no real TM1, DuckDB, snapshots, credentials or corporate data. Runtime data stays in a separate user directory.
- **Offline-first and Windows Portable**: no Python/pip/Node/Git/admin required for end users.
- **Read-only by default**: no mutation of live TM1 or real offline data during analysis; explicit separate authorization for write operations.
- **Large-model discipline**: indexed/scoped/lazy/incremental processing, cancellable jobs, stage-based progress, bounded memory, performance budgets; avoid per-object rebuilding of full graphs.
- **Security**: local-first, redact secrets and sensitive content from logs/exports; user-controlled sharing/export.
- **Engineering quality**: regression tests, deterministic outputs, source citations, documented limitations, stable CLI/Web behavior.
- **Commercial integrity**: no proprietary IBM endorsement claims, respect third-party licenses and customer confidentiality.

## Milestones and release gates

**M1 — Workflow truth**: for a synthetic caller + two source cubes + intermediate + target + conditional/dynamic reference, reconstruct separate execution/data graphs with correct evidence and UNKNOWN; usable on real offline data.

**M2 — Calculation truth**: extract expression AST/IR, value provenance, parameters and coordinate mappings for a documented TI subset; no invented formulas.

**M3 — Module extraction**: extract one bounded functional capability from a large model with declared boundaries, inputs, outputs, dependencies, missing links, and export package.

**M4 — Migration contract**: produce target-neutral specs and Java-oriented design with explicitly unresolved TM1 semantics.

**M5 — Equivalence**: run fixtures and compare expected/actual outputs with traceable tolerances and exception reports.

**M6 — Sellable product**: portable onboarding, robust UX, privacy, licensing strategy, docs, reproducible packaging, realistic performance tests.

A milestone is complete only with executable tests, inspectable artifacts, limitations and no regression in the supported baseline.

## Change control

Every implementation must include: goal and non-goals; repository evidence; minimal design; code; tests; sample evidence-backed output; performance and safety notes; known unknowns; next recommendation. If the task is too broad, deliver a working vertical slice rather than half-built features. Do not delete old user data, rewrite major architecture, push, publish, or access live systems without explicit permission.

## Permanent product test

**Can this change help a user more reliably answer: Where did the data come from? What transformed it? Why did the result arise? How can we reproduce and verify it in a new system?**

If not, it is not a core priority.

## Asset extraction and offline handover — binding product direction (2026-11)

TM1 Insight must make a large existing model understandable and portable as engineering knowledge: discover relevant assets, explain a bounded function from inputs through processing to outputs, and provide an inspectable offline handover. Evidence serves these answers; evidence alone is not the user-facing product. This direction supplements the North Star and preserves all four product layers and the evidence contract above.

- Lead with a concise answer, prioritized objects, key slices and actionable gaps; retain original evidence and uncertainty on demand. A candidate, unknown or unverified result must never be presented as a proven calculation or runtime result.
- Asset importance is a transparent, configurable discovery aid, not an asserted business-criticality fact: show signals, scope, missing coverage and human confirmation; do not rank solely by names or obscure a low-ranked actual dependency.
- Reuse existing parsers, indexed facts and UI components. One write or Rule fact must retain the same identity, direction, evidence and confirmation status across Cube, lineage, architecture and exports; multiple entry points may serve different jobs.
- Read-only browsing, source viewing and navigation must remain responsive independently of expensive analysis. Measure end-to-end cold and warm performance on representative large synthetic and, when authorized, local models; cancellation, resource budgets and versioned cache invalidation are release requirements.
- An offline model package and a bounded functional design package must state their exact scope, model identity, schema/version, checksums, completeness and omissions. Samples are never represented as complete definitions; neither package is automatically a server backup or runtime-equivalence proof. Credentials and business cell data are excluded by default; sharing model metadata and source requires user control.
- Restore navigation context safely across refresh and return where feasible, bound to model identity; temporary browsing does not require draft-saving. Audit actual state paths and preserve existing routes and saved data.
- Record design intent, dimension choices and reusable practices as human-confirmed interpretations linked to source-backed examples and verification, never as inferred business facts. No integrated AI services.
- The phased execution plan and measurable acceptance gates are documented in `docs/PRODUCT_EVOLUTION_OFFLINE_ASSETS.md`. That plan is not a claim that any phase has already shipped.

## 资产提炼优先 — binding direction (2026-11-03 revision)

The product currently proves too much and answers too little. Evidence is the moat, but evidence is not the product surface. TM1 Insight must let a developer answer, within three clicks, **what matters in this model, what it does, and how it is implemented** — then offer the proof on demand. The strategy and phased plan live in `docs/PRODUCT_STRATEGY_2026_11.md`; this section is the binding rule.

### Two-layer output contract

Every analysis must have two layers, in this order:

1. **Answer layer** — a human-consumable conclusion: what this is, the key objects, the supported logic, the explicit gaps, and what the reader should do next. Written so it can go into a review or handover without rework.
2. **Evidence layer** — the source-backed proof, collapsed by default: object, section, location, expression, snapshot, parser rule.

Summarizing is allowed; inventing is not. A conclusion in the answer layer must state its basis and coverage, and must never present a candidate, unknown or unverified result as a proven calculation or runtime result.

### Asset perspective

An **asset map** (`/atlas`) is the first entry point: model-wide assets of every type, ordered by transparent, inspectable technical signals, with per-signal values, explicit coverage gaps and a human-readable export. Ranking is a discovery aid, never an assertion of business criticality: weights are configurable in code, signals are visible on screen, low-ranked real dependencies are never hidden, and human confirmation is recorded separately from static signals.

### Navigation and entry discipline

- First-level entries: workspace (`/`), asset map (`/atlas`), then the **model browsing group** — Cube (`/cubes`), TI (`/processes`), Chore (`/chores`) — then a secondary group for frontend assets and connection settings. Do not add another task entry, and do not replace the three object entries with an aggregate catalog.
- **One feature, one entry.** Every other path must be a deep link that lands in the identical state; no parallel routes with divergent initial state.
- Code generation is a development aid, not an asset-understanding path: it appears inside an object's implementation context, never as a first-level entry.
- Hidden navigation groups are prohibited as a dumping ground. If a feature cannot earn a place in the navigation or an object view, retire it. Legacy routes may keep returning a redirect, never a second UI.
- Dimensions are not a browsing entry: a dimension is read in the context of the cubes that use it. Keeping a standalone dimension browser in navigation is prohibited.

### One object, one page

Cube, TI and Chore are three objects with three different questions, and each keeps its own page. Aggregating them behind a generic "object" screen was tried and retired: it duplicated richer detail pages and forced a second mental model.

- **Cube** (`/cubes` → `/explorer/cube/{name}`) answers *how is this value produced*: dimension structure, formation (write points, slices, rule references), rule text.
- **TI** (`/processes` → `/explorer/process/{name}`) answers *what does this program do*: parameters, sections, source, call relationships, data sources.
- **Chore** (`/chores` → `/explorer/chore/{name}`) answers *when does this run*: schedule basis and ordered steps with explicit missing/duplicate markers.
- Each view is rendered server-side from the URL; switching is a normal navigation, not hidden client state. No view may exist without a URL.

### Lineage belongs to the cube

Data lineage has exactly one canvas and one subject: the cube. `/graph?cube=…` renders it, unchanged in semantics and rendering. A TI has no lineage canvas of its own — its control flow (calls, callers, scheduling) is part of its detail page. Producing a second data-flow canvas for a TI is prohibited: it repeats the cube canvas with a worse entry point.

Business architecture's flow views are folded into the cube detail page's formation section. `/architecture?name=…&kind=…` redirects to the matching detail page; the old read-only canvas workspace survives only behind `view=workbench` until its last user migrates.

### Handoff is an export, not a page

Every Cube and TI detail page links to `/api/object/{kind}/{name}/handoff.md`: a Markdown summary stating scope, facts, upstream/downstream, gaps and the evidence boundary. It is a deliverable a developer can send without editing. It has no page of its own — a separate "handoff view" is a second place to read the same object and is prohibited.

### State discipline

View state that a user can meaningfully return to — selected object, filters, depth, view mode, page — must be encoded in the URL and replayed by the server. A refresh, a back navigation, or a model switch must never silently produce a different canvas. Temporary exploration does not require saving a draft.

### Signal-to-noise rule

UNKNOWN, PARTIAL and "needs confirmation" may appear in the primary view **only when they change the current conclusion**. Otherwise they belong in the evidence layer with one plain-language sentence. A page dense with unresolved markers is a defect, not a display of rigor.

### Feature gate

A feature may enter first-level navigation only if it passes all four checks: it answers exactly one question with a conclusion; it produces a consumable human-readable output; it states its own limits on screen; and it is measurable against an acceptance number. Failing that, it stays in the tool menu or is retired. Retiring a feature is a legitimate product action, reviewed at each release.

### Preserved

The existing lineage canvas, its relations, evidence semantics and read-only guarantees are retained unchanged; only its mount point moved to `/graph?cube=`. The asset perspective is additive information, not a replacement for the graph. No second semantic engine may be introduced: asset signals, lineage, detail pages and exports must read the same facts through the existing parser, store and resolvers.

Identity is resolved case-insensitively and deduplicated: two indexed names that differ only in case are one object, and a detail page never presents one variant's numbers as if they covered both.

No integrated LLM, RAG, AI agent or external AI service. No automated business-criticality judgment. No flattening a large model into an unreadable canvas; large-model views must aggregate, bound and expand on demand.
