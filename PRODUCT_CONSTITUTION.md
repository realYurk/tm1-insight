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

Architecture exports use a versioned deterministic schema containing module, entry_points, cubes, dimensions, processes, rules, chores, execution_relationships, data_relationships, transformation_steps, input_outputs, evidence, unresolved_dependencies and migration_notes. Preserve technical evidence separately from the default presentation. Navigation prioritizes model assets, lineage, architecture and code generation; retain legacy tools and data in advanced tools.

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
