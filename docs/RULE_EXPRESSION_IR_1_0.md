# Rule Expression IR 1.0 (Task 21)

Product pillar: Model Foundation → Lineage & Relationships → Architecture Explorer.
The user can inspect computation structure in the existing Rule result rather than
infer formulas from a list of Cube references. No runtime evaluator is introduced.

## Scope and acceptance

Offline only. Preserve legacy Rule/Feeder fields and conservative LHS ownership.
Acceptance: precedence, balanced nested calls, IF branches, reference identity,
exact source spans, unsupported syntax, bounded resources, legacy store compatibility,
and unchanged pre-existing results when the additive tree is removed.
No UI, Java, cell reads, server calls, or formal database migration.

## Inventory before implementation

Read-only inventory of three requested Cubes plus six large Rule sources:
1,357 Rules and 434 Feeders. Counts include independent Feeder statements, not value flow.
Shared `learning.syntax` tokenizer emits separate symbols for `@=`, `<>`, `>=`, etc.
The expression parser combines only contiguous symbols, longest match first.
Observed numeric/string literals, comparisons, arithmetic, parentheses, nested IF,
DB, ATTRS/N, ELISANC, area references, !Dimension, STET/CONTINUE, logical `&`/`%`,
string concatenation `|`, both `/` and TM1 safe division `\`.
No `^` in this inventory: exponentiation remains unsupported rather than asserting
unverified TM1 precedence/associativity. ELISPAR has synthetic coverage but no occurrence
in the selected real sources. Additional observed functions include SIGN, TABDIM,
CONSOLIDATECHILDREN, LONG, SUBST, DIMIX and date/number conversion helpers.
Their parameter trees are retained; unsupported function semantics stay PARTIAL.
Detailed per-Cube token/function counts and actual excerpts are private local artifacts,
not bundled with source or sample data.

## Additive contract

`rhs.expression_ir` root has `version=rule-expression-1`, `cube`, `source_hash`,
`runtime_validated=false`. Every node has:

* `type`, exact `raw`, ordered `children`;
* `source`: section=`rule`, 1-based line/column, zero-based offset/end_offset
  (exclusive), relative to original Rule source;
* `structure_status`: PARSED, PARTIAL or UNKNOWN (syntax only);
* `status`: PARSED for supported static structure without recorded unresolved inputs,
  PARTIAL for unresolved metadata/functions/children, UNKNOWN for unsupported structure;
* `semantic_status`: STRUCTURE_ONLY or UNCONFIRMED; **never runtime proof**;
* `unresolved_reasons` propagated from children; bounded `tree_depth`.

Nodes: NumberLiteral/StringLiteral (`value` preserves lexical form), Identifier (`name`),
RegionReference (`dimension`), AreaReference (`area`, existing conservative resolver),
DBReference (`name`, `reference` from existing resolver, children=arguments),
UnaryOperation/BinaryOperation (`operator`), FunctionCall (`name`),
ConditionalExpression (IF children=condition/then/else), SpecialExpression, UnknownExpression.
Invalid IF arity is PARTIAL; callers must inspect status before interpreting branches.
Known function names alone do not establish complete semantics.

Precedence low→high: `%`, `&`, numeric/string comparisons, `|`, `+ -`, `* / \`, unary.
Binary operators are left associative. Parentheses expand the contained node's source
span without introducing an invented calculation operation. No expression evaluation.
Unknown functions retain all successfully parsed arguments and nested DB evidence.
Unsupported trailing syntax preserves the whole raw expression and parsed prefix.
Malformed grouping falls back to UnknownExpression; no fabricated children.

## Reuse, compatibility and limits

Uses shared syntax tokens; bounded precedence-climbing follows existing Calculation parser
pattern. Reuses existing area and DB metadata resolvers; no second architecture engine.
Legacy `rhs.expression`, `rhs_kind`, references, conditions, status and unknowns are unchanged.
IR-specific reasons live in the new subtree; consumers must inspect its status separately.
Feeder has no expression_ir. No persisted schema change; old snapshots parse on read.
Rule revision 2→3; Architecture revision 10→11 invalidates derived architecture cache keys.
Root source_hash changes with Rule source; expression parser has no cache.
Maximum 12,000 tokens/expression, recursive/tree depth 64. Resource limits yield UNKNOWN.
Named DB coordinates (`'Dimension':'Member'`), scientific/leading-dot literals,
exponentiation and unsupported syntax remain UNKNOWN. No region/member runtime values,
hierarchy/attribute validation, consolidation, rule priority or numeric equivalence claims.

## Validation

See the private Task 21 delivery report for exact test outputs, real source examples,
before/after comparisons, performance and DB integrity verification. Tests use synthetic
rules and isolated/in-memory stores; real collections are opened read-only.
