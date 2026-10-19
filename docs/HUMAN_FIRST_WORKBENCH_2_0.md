# Human-First Workbench 2.0

## Product outcome

Architecture Explorer now opens with the existing Functional Flow projection:
business flow, objects and roles, then actions and key slices. Technical evidence
remains available on demand. This changes presentation, not calculation semantics.
The shared flow object also drives Markdown and Mermaid exports.

## Audit and implementation

Previously architecture opened with technical summaries, Cube Rule source followed
semantic/Feeder details, dimension buttons appended panels, and source fragments
used several rendering paths. The existing Formation, Workflow, Rule IR, unified
relations, graph queries and export task are reused rather than replaced.

- `human_workbench.py` projects Rule statements into a paginated summary table.
- `workbench-tables.js` presents objects, actions, Rule summaries, processing and
  per-write Formation summaries. Evidence expands locally. Fixed members, runtime
  variables and unconfirmed expressions remain distinct.
- `architecture.js` manages one toggleable dimension panel, including switching,
  close, Esc and stale-request protection. Expert relations remain available.
- Cube Rule source opens first; semantic and Feeder analysis follows below.
- `syntax.js` provides one offline source viewer with safe lexical highlighting,
  line numbers, original-text copying and a large-file plain-text fallback.
  Existing code generation copying uses the same original-text accessor.
- Graph queries retain call semantics, with shared node/depth budgets and cycle
  protection. Dense sides stack and fold; write slices load lazily from Formation.
- Navigation groups model browsing, architecture, lineage and management; code
  generation remains a primary entry. Legacy routes and advanced tools survive.
- Home search accepts Cube or Process names and prefix discovery.

No parser, value-dependency rule, formal database schema or business interpretation
engine is changed. An indexed read and write in one TI is still not proof of value
transfer. Source-backed helper folding remains the responsibility of existing
architecture analysis, not a new name-based classifier in this presentation layer.

## Export contract

Existing exports remain available. Architecture task export additionally accepts:

- `format=human-markdown`: business flow, objects, actions, key slices, compact
  Rule summaries and important limitations, without the technical evidence appendix.
- `format=ai-package`: ZIP with schema `tm1-analysis-package-1`, Manifest.json,
  canonical Architecture.json, FunctionalFlow.json, BusinessFlow.md, Diagram.mmd,
  verified Process/Rule sources and recorded dimension/Process metadata.

The package stores canonical analysis once and uses references. Its manifest records
file sizes and SHA-256 checksums. ZIP timestamps and ordering are deterministic.
Source identity is checked before inclusion; failure does not publish a partial ZIP.
Credential-like source values are redacted while preserving positions. Original
source hashes and exported file checksums are distinct.

Limits: 64 MiB uncompressed, 500 Process sources, 200 dimensions, and samples of up
to 25 records per dimension metadata category. Missing or sampled data is explicitly
marked; “full” means the available bounded analysis scope, not the entire server.
No connection settings or cell values are included. Exports may still contain private
model source and should be shared only at the user's discretion.

## Verification and compatibility

Focused tests cover conservative Rule summaries, old routes, defaults, source order,
source escaping/copy fidelity, graph budgets/cycles, deterministic manifests,
credential redaction, missing old metadata, source mismatch and size failure.
Navigation assertions were updated to allow the explicitly requested folded tools;
their routes were retained rather than deleted.

Real local-model acceptance covered four Cube entries and two Process entries,
including dimension toggle interactions, Rule source order, dense lineage and all
export modes. Private acceptance exports and screenshots are kept outside Git.
No TM1 server calls or formal model writes are needed. Existing snapshot/API fields
remain compatible. Portable packaging is unchanged; no new binary was built.

## Known limits

Static source does not prove runtime contributions, scheduling order or dynamic
coordinates. Missing Data Row Variables are not inferred from variable names.
Lexical highlighting does not validate Rule or TI semantics. Very large sources
retain plain text and copying instead of expensive highlighting. Browser clipboard
success feedback was exercised; exact original CRLF/trailing-space preservation
is additionally verified in an isolated source-viewer test.

Next work should follow user acceptance of these views and close specific missing
metadata evidence, rather than expanding the presentation into another engine.
