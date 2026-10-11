# TM1 Insight — AI Development Constitution

> This document is the permanent engineering constitution for the TM1 Insight project.
>
> Any AI coding assistant working on this repository MUST read and follow this document before making architectural or code changes.

# 1. Project Identity

## Project Name

**TM1 Insight**

Former repository/project name:

```
tm1-suite
```

The project is evolving from a TM1 utility collection into a professional **TM1 Model Intelligence & Engineering Platform**.

Suggested repository name:

```
tm1-insight
```

Do not rename the repository or perform large-scale branding changes unless explicitly instructed by the project owner.

# 2. Product Definition

TM1 Insight is NOT primarily:

- an AI assistant
- a chatbot
- an Excel utility
- a TM1 query tool
- a TI code editor
- a simple lineage viewer
- a graph visualization demo
- a collection of unrelated TM1 utilities

TM1 Insight is:

> **A professional software platform for understanding, analyzing, tracing, governing, and evolving complex IBM Planning Analytics / TM1 models.**

The fundamental product goal is:

> **Make complex TM1 models understandable, traceable, analyzable, governable, and maintainable through software.**

The core principle is:

> **Understand the model before trying to automate the model.**

# 3. Current Strategic Decision: NO AI

## Critical rule

### AI is OUT OF SCOPE for the current product roadmap.

Do NOT introduce:

- LLM
- RAG
- Agent
- AI chatbot
- AI Analyst
- vector database
- embeddings
- prompt orchestration
- AI-generated TM1 code
- AI model dependency
- external AI API dependency

unless the project owner explicitly changes this decision.

The project must first become extremely strong through deterministic software engineering.

# 4. Why AI Is Deliberately Excluded

The core technical difficulty of TM1 is not generating text.

The difficult problem is:

> **Understanding the actual structure and behavior of a TM1 model.**

TM1 Insight must therefore first solve:

```
TM1 Server
    ↓
Metadata Collection
    ↓
Snapshot
    ↓
Code Parsing
    ↓
Symbol Resolution
    ↓
Dependency Analysis
    ↓
Lineage
    ↓
Model Graph
    ↓
Impact Analysis
    ↓
Model Health
    ↓
Version Comparison
    ↓
Change Intelligence
```

Only after this foundation becomes mature may an AI layer be considered.

If AI is ever introduced in the future, it must consume the deterministic Model Intelligence layer rather than replace it.

Future architecture may eventually become:

```
TM1 Insight
│
├── Model Intelligence Engine
│
├── Explorer
├── Lineage
├── Impact
├── Governance
├── Compare
│
└── Optional AI Layer
```

AI must remain an optional interface layer.

# 5. Product Vision

TM1 Insight should eventually provide a complete understanding of a TM1 environment.

A user should be able to answer questions such as:

## Model Discovery

- What Cubes exist?
- What Dimensions exist?
- What Processes exist?
- What Chores exist?
- What Rules exist?
- What Applications or frontend assets exist?

## Code Understanding

- What does this Process do?
- Which Cubes does it read?
- Which Cubes does it write?
- Which Dimensions does it reference?
- Which variables influence the target?
- Which Processes does it call?

## Data Lineage

- Where does this data come from?
- Which Process writes it?
- Which Process reads it?
- Which Cube is the source?
- Which Cube is the target?
- What transformations occur?

## Dependency Analysis

- What depends on this Cube?
- What depends on this Dimension?
- What calls this Process?
- What Processes are indirectly affected?

## Impact Analysis

If I change:

```
Cube
Dimension
Process
Rule
Subset
Chore
```

what could be affected?

## Model Health

- Which objects are unused?
- Which objects appear orphaned?
- Which Processes are highly coupled?
- Where are dependency risks?
- Where are broken references?
- Where are potential dead objects?
- Where are architecture problems?

## Model Evolution

- What changed between two snapshots?
- Which Processes changed?
- Which Rules changed?
- Which dependencies changed?
- What was added?
- What was deleted?
- What may be affected by the change?

This is the long-term product direction.

# 6. Core Product Philosophy

TM1 Insight follows seven principles.

## 6.1 Correctness over feature count

A correct lineage result is more valuable than ten flashy features.

Never sacrifice correctness for UI effects.

## 6.2 Deterministic software over AI

Important model conclusions must come from actual model evidence.

Do not guess.

Do not hallucinate.

Do not infer a dependency merely because two object names look similar.

## 6.3 Explainability

Every important result should eventually be traceable to:

```
Object
Process
Cube
Rule
Code
Dependency
Snapshot
Evidence
```

A user should be able to understand:

> Why did TM1 Insight say these two objects are related?

## 6.4 Offline-first

After metadata extraction, as much analysis as practical should work locally.

The product should not require permanent access to the TM1 Server.

The current DuckDB + Parquet architecture should be preserved unless a strong technical reason requires change.

## 6.5 Incremental evolution

Do not rewrite the entire project.

Prefer:

```
existing implementation
        ↓
extract abstraction
        ↓
add tests
        ↓
introduce better implementation
        ↓
migrate gradually
```

over:

```
delete everything
        ↓
rewrite everything
```

## 6.6 Backward compatibility

Existing functionality is valuable.

Do not casually break:

- CLI commands
- existing APIs
- database structures
- exported data
- existing ingestion
- existing web pages
- existing user workflows

Breaking changes require explicit justification.

## 6.7 Small architecture, deep capability

Do not introduce complexity merely because the project is becoming more serious.

Avoid premature:

- microservices
- Kubernetes
- distributed systems
- event buses
- message queues
- complex agent frameworks
- unnecessary cloud infrastructure

A well-designed modular Python application is sufficient unless evidence proves otherwise.

# 7. Target Architecture

The long-term architecture is:

```
                    TM1 Server
                        │
                        ▼
                ┌───────────────┐
                │   Collector   │
                │ Metadata/Data │
                └───────┬───────┘
                        │
                        ▼
                ┌───────────────┐
                │    Snapshot   │
                │ Immutable     │
                │ Model State   │
                └───────┬───────┘
                        │
                        ▼
             ┌─────────────────────┐
             │ Model Intelligence  │
             │      Engine         │
             └──────────┬──────────┘
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
     Parser          Resolver         Analyzer
        │               │                │
        ▼               ▼                ▼
       AST          Symbol Graph       Lineage
        │               │                │
        └───────────────┼────────────────┘
                        ▼
                ┌───────────────┐
                │  Model Graph  │
                └───────┬───────┘
                        │
          ┌─────────────┼──────────────┐
          ▼             ▼              ▼
       Explorer       Impact        Governance
          │             │              │
          └─────────────┼──────────────┘
                        ▼
                Snapshot Compare
                        │
                        ▼
                Change Intelligence
```

The current repository does not need to implement every layer immediately.

The architecture exists to guide incremental development.

# 8. Core Technical Direction

The most important technical evolution is:

```
TM1 Code
   ↓
Lexer / Parser
   ↓
AST
   ↓
Symbol Resolver
   ↓
Dependency Resolver
   ↓
Lineage Engine
   ↓
Model Graph
   ↓
Impact / Health / Compare
```

Do not continue indefinitely with increasingly complicated regular expressions if a real parser architecture becomes necessary.

Regex may remain useful for simple extraction.

However, important semantic analysis should gradually move toward structured parsing.

# 9. Domain Model

TM1 Insight should gradually establish a clear internal domain model.

Important entities include:

```
Model
Instance
Snapshot

Cube
Dimension
Hierarchy
Element
Subset

Process
Chore

Rule
Feeder

Application
Workbook
Worksheet

Dependency
Lineage
Reference
Change
Impact
HealthFinding
```

Not every entity needs to be implemented immediately.

The purpose is to prevent the system from becoming a collection of unrelated database tables.

# 10. Snapshot Is a First-Class Concept

A snapshot represents a point-in-time state of a TM1 model.

Conceptually:

```
Snapshot
├── Cubes
├── Dimensions
├── Processes
├── Chores
├── Rules
├── Subsets
├── Applications
├── Frontend assets
└── Dependency information
```

Snapshots should be treated as immutable historical states.

Do not silently mutate an old snapshot to represent a new model state.

Instead:

```
Snapshot A
    ↓
Snapshot B
    ↓
Snapshot C
```

This is the foundation for:

- comparison
- change detection
- historical analysis
- impact analysis
- auditing
- future governance

# 11. Model Graph

The Model Graph is one of the most important long-term assets of TM1 Insight.

It should eventually represent relationships such as:

```
Process → Process
Process → Cube
Process → Dimension
Process → Subset
Rule → Cube
Rule → Cube
Chore → Process
Frontend → Cube
Frontend → Process
Cube → Dimension
```

The graph should represent real model evidence.

Do not generate decorative graph relationships.

A graph edge should have a reason.

For example:

```
Process A
    │
    │ CellPutN
    ▼
Cube X
```

The system should eventually retain evidence such as:

```
source object
target object
relationship type
source code
location
confidence
snapshot
```

# 12. Parser Architecture

The parser must eventually distinguish between:

### Syntax

What code is written?

and:

### Semantics

What does the code actually reference?

For example:

```
CellPutN(
    value,
    cube_name,
    dim1,
    dim2,
    dim3
);
```

The system should eventually understand:

```
operation = CellPutN
target_cube = resolved cube
coordinates = resolved expressions
source_location = code position
```

Do not stop at:

```
"CellPutN appears in this file"
```

The goal is:

> **Understand what the statement means.**

# 13. Symbol Resolution

Symbol resolution is critical.

The system must eventually distinguish:

```
literal
variable
parameter
expression
function result
resolved object
unresolved reference
```

For example:

```
sCube = 'Sales';
CellPutN(vValue, sCube, ...);
```

should ideally resolve:

```
sCube
   ↓
Sales
   ↓
Cube: Sales
```

rather than simply reporting:

```
Cube: sCube
```

Resolution must be conservative.

If something cannot be resolved reliably:

```
status = unresolved
```

Do not invent a result.

# 14. Process Calls

The system must understand:

```
ExecuteProcess(...)
```

and eventually support:

```
Process A
    ↓
Process B
    ↓
Process C
```

including indirect relationships.

This is essential for real dependency and impact analysis.

# 15. Lineage

Lineage should evolve from simple textual matching toward semantic lineage.

Long-term lineage should answer:

```
Where does this value come from?

Which process writes it?

Which process reads it?

Which cube is involved?

Which dimensions define the slice?

Which process calls the process?

What upstream source contributes to the value?

What downstream objects depend on it?
```

Lineage results must be evidence-based.

# 16. Impact Analysis

Impact Analysis is one of the most important future capabilities.

Examples:

```
If Cube X changes:
    ↓
Processes reading Cube X
    ↓
Processes called by those processes
    ↓
Downstream Cubes
    ↓
Rules
    ↓
Frontend assets
```

Likewise:

```
If Dimension X changes:
    ↓
Cubes using Dimension X
    ↓
Rules
    ↓
Processes
    ↓
Frontend assets
```

The system should distinguish:

```
direct dependency
indirect dependency
potential dependency
unresolved dependency
```

Do not treat all relationships as equal.

# 17. Model Health

Eventually TM1 Insight should calculate model health.

Potential categories:

```
Architecture
Dependencies
Unused Objects
Broken References
Code Quality
Coupling
Complexity
Frontend Risk
Data Flow Risk
Governance
```

Examples:

```
High process coupling
Potential orphan process
Unused cube
Broken reference
Circular dependency
Process with excessive responsibilities
Frontend reference to missing cube
```

Health analysis should be deterministic and rule-based.

Do not use AI-generated scores.

# 18. Technical Debt

TM1 Insight should eventually identify technical debt.

Examples:

```
Unused objects
Duplicate logic
Orphan processes
Broken dependencies
Highly coupled processes
Large complex processes
Dead rules
Unused dimensions
Unreferenced subsets
Suspicious frontend assets
```

Every finding should contain:

```
finding
severity
reason
evidence
affected objects
recommended direction
```

Do not generate meaningless “health scores” without evidence.

# 19. Snapshot Compare

Eventually support:

```
Snapshot A
       ↓
Compare
       ↓
Snapshot B
```

Results:

```
Added
Removed
Changed
Unchanged
```

For example:

```
Process:
    P_A added
    P_B modified
    P_C removed

Cube:
    Cube_X unchanged
    Cube_Y modified

Dimension:
    Dim_A added elements
```

Eventually compare dependency graphs as well.

# 20. Change Intelligence

Snapshot comparison should eventually lead to:

> What changed, and what could that change affect?

Example:

```
Process B changed
      ↓
Process B writes Cube X
      ↓
Cube X feeds Process C
      ↓
Process C writes Cube Y
      ↓
Frontend uses Cube Y
```

The product can then report:

```
Potential downstream impact:
Cube X
Cube Y
Process C
Frontend Workbook Z
```

This is a major long-term differentiator.

# 21. Existing Product Capabilities

Do not destroy the useful capabilities already present in the project.

Current capabilities include concepts such as:

- global search
- Cube explorer
- Process explorer
- TI code inspection
- MDX reverse lookup
- lineage
- knowledge graph
- code generation
- frontend Excel asset audit
- CLI
- offline data package
- DuckDB + Parquet storage
- model ingestion
- web interface

These should be progressively improved and integrated into the new architecture.

Do not rewrite them merely for stylistic reasons.

# 22. Existing UI

Current conceptual pages include:

```
/
 /cubes
 /processes
 /graph
 /codegen
 /audit
 /settings
```

The UI is not the first priority.

Do not perform a large frontend redesign unless:

1. the information architecture is wrong
2. usability is significantly blocked
3. the new domain model requires it

The priority is:

```
Core engine
    >
Data model
    >
Parser
    >
Resolver
    >
Lineage
    >
Impact
    >
Governance
    >
UI polish
```

# 23. Database

Current architecture:

```
DuckDB
+
Parquet
```

Keep this architecture unless a clear technical reason requires change.

Do not replace DuckDB with:

```
PostgreSQL
MySQL
Neo4j
MongoDB
```

simply because the project is becoming larger.

A graph representation does NOT automatically require a graph database.

The Model Graph may initially be represented using relational tables.

Only introduce a graph database if actual requirements prove DuckDB insufficient.

# 24. Dependency Policy

Avoid unnecessary dependencies.

Before adding a dependency ask:

1. Why is it necessary?
2. Can the standard library solve it?
3. Can the existing stack solve it?
4. Does it create long-term maintenance cost?
5. Is it stable?
6. Does it materially improve the product?

Do not add dependencies merely for convenience.

# 25. Architecture Rules

Do NOT introduce:

- microservices
- Kubernetes
- message queues
- event-driven architecture
- distributed graph systems
- vector databases
- AI agent frameworks
- cloud-only infrastructure

unless explicitly requested by the project owner.

The default architecture should remain:

```
Python
FastAPI
DuckDB
Parquet
Existing frontend
```

with clean internal modules.

# 26. Code Quality

Prefer:

```
small modules
clear interfaces
typed data
explicit dependencies
testable functions
deterministic behavior
clear naming
```

Avoid:

```
giant files
global state
magic constants
hidden side effects
duplicated logic
deep circular imports
untyped data everywhere
```

Do not over-engineer.

# 27. Testing Philosophy

Every important new capability should have tests.

Especially:

```
Parser
Resolver
Lineage
Dependency analysis
Snapshot
Snapshot comparison
Impact analysis
Audit
CLI
```

Tests must verify real behavior.

Do NOT:

- write tests only to increase coverage
- mock everything
- test implementation details unnecessarily
- modify tests merely to make failing code pass
- weaken assertions to hide bugs

A failing test is information.

# 28. Regression Protection

Before modifying core logic:

```
read existing tests
```

After modifying core logic:

```
run targeted tests
run regression tests
run full test suite when practical
```

Do not assume a local test passing means the system is safe.

# 29. CLI Compatibility

Existing CLI commands are part of the product.

Do not casually remove or rename commands.

Existing concepts include:

```
status
query
audit
ingest
ingest --no-export
check
web
```

If a breaking CLI change is truly necessary:

1. explain why
2. propose migration
3. preserve compatibility where practical

# 30. Public API Compatibility

Treat existing APIs as contracts.

Before changing:

```
function signatures
CLI arguments
database schema
API routes
configuration fields
export formats
```

check existing usage.

Prefer additive changes.

If a breaking change is unavoidable, explicitly document it.

# 31. Data Safety

Never destroy user data silently.

Never:

```
delete snapshots
overwrite historical model state
drop tables without migration
destroy exported data
```

without explicit instruction.

When changing storage structures, consider:

```
migration
backward compatibility
versioning
rollback
```

# 32. Security

TM1 credentials are sensitive.

Never:

- commit credentials
- print passwords
- expose tokens in logs
- include secrets in generated reports
- hardcode server credentials
- store secrets in source code

Respect the existing `.env` configuration approach.

# 33. Commercialization Direction

TM1 Insight should be architected so that it can eventually support different editions.

Potential future structure:

### Community

```
Model Explorer
Basic Lineage
Graph
Offline Snapshot
CLI
```

### Professional

```
Advanced Lineage
Impact Analysis
Model Health
Technical Debt
Snapshot Compare
Architecture Reports
Frontend Audit
Advanced Code Analysis
```

### Enterprise

```
Multi-instance
Multi-user
RBAC
SSO
Central Repository
Scheduled Scans
Historical Snapshots
Audit Trail
REST API
Custom Governance Rules
```

These are future directions, not current implementation requirements.

Do not implement commercial complexity prematurely.

# 34. GitHub Project Quality

The project should gradually become a professional open-source project.

Important files:

```
README.md
LICENSE
CHANGELOG.md
ROADMAP.md
ARCHITECTURE.md
CONTRIBUTING.md
SECURITY.md
```

Potential future documentation:

```
docs/
├── architecture/
├── parser/
├── lineage/
├── snapshot/
├── impact/
├── governance/
└── development/
```

The repository should eventually communicate:

> This is a serious TM1 engineering product.

# 35. README Philosophy

The README should lead with:

```
Why does TM1 Insight exist?
What problem does it solve?
Who is it for?
Why is it different?
What can it do?
```

Do not lead with a giant installation manual.

The core statement should communicate the fundamental value:

> **Understand your TM1 model. Trace dependencies. Analyze impact. Govern complexity.**

# 36. Development Workflow for AI Coding Assistants

When the project owner asks you to implement something, follow this process.

## Step 1 — Read before changing

Inspect relevant:

```
README
pyproject
requirements
src
tests
database/storage
ingestion
lineage
API
CLI
configuration
```

Do not guess the architecture.

## Step 2 — Understand existing implementation

Before proposing code, determine:

```
Where does this functionality currently live?
What interfaces already exist?
What data structures already exist?
What tests already exist?
What dependencies exist?
```

## Step 3 — Produce an implementation plan

For non-trivial changes, first provide:

```
Implementation Plan

1. Current implementation
2. Problem
3. Proposed architecture
4. Files to modify
5. Files to create
6. Database impact
7. API impact
8. Migration requirements
9. Test strategy
10. Risks
11. Rollback strategy
```

Do not immediately rewrite the project.

## Step 4 — Keep changes focused

Prefer small increments.

Example:

```
Task 1
Domain model

Task 2
Snapshot abstraction

Task 3
Parser interface

Task 4
Resolver

Task 5
Lineage refactor
```

rather than:

```
Rewrite TM1 Insight
```

# 37. Large Changes Require Caution

Before a large architectural change:

- explain the reason
- explain alternatives
- explain migration
- explain risk
- explain compatibility impact

Do not silently perform a large rewrite.

# 38. Never Do These Things

Unless explicitly instructed, NEVER:

1. Rewrite the entire project.
2. Delete existing functionality.
3. Replace DuckDB just because another database is popular.
4. Add AI.
5. Add an LLM.
6. Add RAG.
7. Add a vector database.
8. Add microservices.
9. Add Kubernetes.
10. Replace the frontend framework without strong reason.
11. Break CLI compatibility.
12. Destroy existing data.
13. Modify database schema without considering migration.
14. Add dependencies casually.
15. Create giant modules.
16. Hide errors instead of fixing them.
17. Fake test results.
18. Remove failing tests just to make CI green.
19. Generate meaningless architecture diagrams.
20. Implement features merely because they sound impressive.

# 39. Current Development Era

The project is currently in:

# Era 0 — Foundation

The immediate objective is NOT to add many visible features.

The immediate objective is to make the architecture capable of supporting years of development.

Priority:

```
1. Domain Model
2. Snapshot
3. Parser Architecture
4. Symbol Resolver
5. Dependency Model
6. Lineage Engine
7. Tests
8. Impact Analysis
9. Model Health
10. Snapshot Compare
11. Change Intelligence
12. Productization
```

Do not skip directly to 8–12 without strengthening 1–7.

# 40. Recommended Evolution

## v0.2 — Foundation

Focus:

```
Domain Model
Snapshot
Storage abstraction
Parser interface
Resolver interface
Dependency model
Test foundation
```

## v0.3 — Model Intelligence

Focus:

```
AST
Symbol resolution
Cube resolution
Process resolution
ExecuteProcess
CellGet*
CellPut*
Rule dependencies
Dependency graph
```

## v0.4 — Impact

Focus:

```
Impact Analysis
Direct dependency
Indirect dependency
Dependency risk
Change propagation
```

## v0.5 — Governance

Focus:

```
Model Health
Unused objects
Orphans
Broken references
Coupling
Complexity
Technical debt
```

## v0.6 — Lifecycle

Focus:

```
Snapshot Compare
Model Diff
Dependency Diff
Rule Diff
Process Diff
Change Impact
```

## v0.7+

Focus:

```
Architecture Reports
Governance Rules
Advanced Frontend Analysis
Model Documentation
CI/CD integration
Deployment analysis
```

AI is NOT part of this roadmap.

# 41. Definition of a Mature TM1 Insight

The project should eventually be able to take an arbitrary TM1 model and construct a reliable internal representation:

```
TM1 Instance
      ↓
Snapshot
      ↓
Objects
      ↓
Code
      ↓
AST
      ↓
Symbols
      ↓
References
      ↓
Dependencies
      ↓
Lineage
      ↓
Graph
      ↓
Impact
      ↓
Health
      ↓
History
```

The ultimate goal is:

> **TM1 Insight understands the structure and relationships of a TM1 model as deeply as practical through deterministic program analysis.**

That is the product.

# 42. Engineering Principle

Always ask:

> **Does this change make TM1 Insight understand TM1 better?**

If yes, it is probably aligned.

If it only makes the UI prettier:

> lower priority.

If it adds a flashy feature without improving model understanding:

> probably reject.

If it adds AI before the model is understood:

> reject.

If it improves:

```
parsing
resolution
lineage
dependency
impact
history
governance
```

then it is likely strategically valuable.

# 43. Role of the AI Coding Assistant

The AI coding assistant is NOT the product architect.

The project owner decides:

```
product direction
priorities
major architecture
breaking changes
commercial strategy
```

The coding assistant should act as:

```
Senior Software Engineer
+
Architectural Reviewer
+
Test Engineer
+
Code Reviewer
```

It must not independently redefine the product.

# 44. When Unsure

If there are multiple valid approaches:

Do NOT silently choose the most complicated one.

Prefer:

```
simpler
testable
backward compatible
incremental
reversible
```

If a decision could materially affect the architecture, stop and explain the options.

# 45. Final Rule

The most important sentence in this entire document is:

> **Do not build a collection of TM1 features. Build a system that understands TM1 models.**

Everything else follows from this.

# TM1 Insight

### Understand.

### Trace.

### Analyze.

### Govern.

### Evolve.

**Build the Model Intelligence Engine first.**