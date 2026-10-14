# TM1 Insight — Instructions for Coding Agents

Before planning or editing, read `PRODUCT_CONSTITUTION.md` in full. Treat it as the product-level source of truth; repository reality and explicit user instructions govern implementation details. Do not silently reinterpret the North Star as generic AI summaries, documentation generation, or an admin dashboard.

Preserve its four layers: Model Foundation → Lineage & Relationships → Architecture Explorer → human-confirmed Business Interpretation. Default architecture is data objects → processing steps → results, with technical evidence expandable. Fold helpers by source-backed effects, never by invented semantics or simple name filtering. Code generation remains a primary navigation entry. No integrated AI services.

## Required operating loop

1. **Inspect** relevant source, tests, README, data contracts, and git status. Do not assume README describes implemented behavior.
2. **State** the user problem, affected product pillar, scope, non-goals, risks, and measurable acceptance tests.
3. **Trace** current evidence/semantics before adding a new engine. Reuse existing parser/resolver/dependency/lineage/store/UI when possible.
4. **Implement** the smallest complete vertical slice; preserve compatibility, software/data separation, and offline/portable constraints.
5. **Verify** with focused tests, full regression where feasible, and a synthetic example covering dynamic UNKNOWN. Never claim tests ran if they did not.
6. **Report** files changed, behavior, evidence examples, tests, performance, limitations, and the next highest-value task.

## Hard rules

- Never fabricate business meaning, execution order, value lineage, formula, or code evidence.
- Distinguish invocation, dependency, data transformation, static inference, and runtime proof.
- Unknown is a valid result; unsupported syntax must not silently produce certainty.
- Do not implement mandatory AI/LLM/RAG/vector DB.
- Do not bundle or mutate company data; do not expose secrets in output or logs.
- Large models require scoped queries, indexed graph reuse, progress, cancellation and bounded resource use.
- Do not perform destructive operations, remote pushes, releases or live TM1 writes without explicit authorization.

## Completion report format

1. Product outcome and pillar
2. Code evidence inspected
3. Implementation and files
4. Example workflow / formula / module with source evidence
5. Test commands and exact outcomes
6. Compatibility, data safety and performance
7. UNKNOWN and limitations
8. Recommended next vertical slice
