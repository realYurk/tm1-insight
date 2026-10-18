# Data Row Lineage 1.0

Goal: prove a VIEW row variable's contribution to a write value using recorded
metadata and the existing use/definition DAG. No TI execution, numeric cell
collection, new parser, AI, Java generation, or Workbench redesign.

## Root cause and pipeline

- `tm1/client.py::fetch_process` previously omitted `Process.variables` entirely.
  It looked for nested `data_source`/`datasource`; the installed TM1py Process
  actually exposes flat `datasource_type`,
  `datasource_data_source_name_for_server`, and `datasource_view` properties.
  Those actual properties now have a tested fallback. Parameter Default=0 is
  preserved rather than lost by truthiness.
- `collector.py::_map_process` deliberately discarded datasource and detailed
  parameters. It now preserves optional variables/datasource/source_view, and
  adds `parameter_definitions` while retaining legacy name-only `parameters`.
- Snapshot persistence already preserves arbitrary JSON fields. The canonical
  schema adds optional fields; existing version-1 snapshots remain readable.
- The old DuckDB `processes` table has eight columns and no Variables column.
  Keep it unchanged: `process_source_metadata(process_name,payload)` is an
  additive table, populated during explicit Loader ingest or metadata import.
  Read-only analysis detects old databases without creating/migrating tables.
- The existing worksheet previously treated any undefined Data symbol as
  UNKNOWN. Recorded row definitions now enter the existing DAG at row Section
  boundaries; reassignment, branch merges and unknown functions retain existing
  conservative behavior. Metadata reassignment across Sections stays UNKNOWN.

## Evidence contract

`data-row-1` adds these fields to per-write formation results:

| Field | Meaning |
| --- | --- |
| data_source_variable_bindings | Recorded name, type, source column Position and byte bounds; field status separately recorded |
| source_view_binding | Cube/View identity, code or metadata basis, Native/MDX kind and layout status |
| source_coordinate_mapping | Only native extraction-layout correspondence supported by matching source Cube order |
| data_row_value_dependencies | Only row symbols reached from the write VALUE DAG, excluding coordinate/control-only uses |
| value_definition_chain | Original assignments and Section/line/column evidence |
| target_write_binding | Write operation, target Cube and original source location |
| unresolved_binding_reasons | Specific missing/stale/dynamic/unsupported metadata reasons |

Definition and column position do **not** prove a source field. A source field
does **not** prove complete runtime flow. Static per-row expressions do **not**
prove which rows execute, their values, aggregate contribution or equivalence.

v1 requires all of the following to identify a cell value column:

1. Metadata's four-Section source hash matches the selected Process.
2. The actual binding is recorded, or safely resolved by the existing Prolog
   datasource parser. Dynamic/conditional overrides block stored defaults.
3. The recorded bound view is a NativeView with matching Cube/name, and is not
   rebuilt or passed through unanalysed Process invocations in this TI.
4. Source Cube dimension order captured with view metadata matches the local
   complete, unique ordered Cube structure and known Dimension catalog.
5. Variables have unique valid names, unique contiguous 1-based source column
   positions, one String field per source dimension, and one endmost
   Numeric/String value field. A declared variable's name has no semantic role.

Only this combined contract associates native source columns with Cube
dimensions. Position alone never does. StartByte/EndByte are preserved as
metadata and are not used as VIEW coordinates. MDX views, dimension/cell
properties, multiple value columns, implicit slicers and dynamic view layouts
remain UNKNOWN. Multiple measure members in a native view remain distinct
row coordinates; there is no invented fixed metric or aggregation.

The native-order rule is backed by [IBM's cube datasource documentation](https://www.ibm.com/docs/en/planning-analytics/3.1.0?topic=source-define-cube-view-data).
The field/rowset distinction and endmost value convention are described in
[IBM's VIEW rowset guidance](https://www.ibm.com/support/pages/change-variable-order-mdx-views-used-turbointegrator-data-source).
MDX ordering is intentionally not inferred across server versions/layouts.

## Small verified example

Recorded NativeView `Cube_A/Input`: dimension order `[Scenario,Product]`;
variables `vScenario:String:1`, `vProduct:String:2`, `vValue:Numeric:3`.
Target Cube order is `[Product,Scenario]`.

```text
alias = vValue;
nResult = alias * 2;
If(vScenario @= 'ACT');
  CellPutN(nResult, 'Cube_B', vProduct, vScenario);
EndIf;
```

The existing DAG yields the conditional static expression:

```text
Cube_B[Product=vProduct,Scenario=vScenario]
  = Cube_A[Scenario=vScenario,Product=vProduct] * 2
```

Recorded metadata confirms the value field; assignment/use locations confirm
the transformation. The condition and target coordinates remain explicit.
No runtime or actual amount is claimed. Rename a dimension field to `vValue`,
add a second numeric column, remove NativeView evidence, overwrite the variable
or pass it through an opaque function: the complete Cube formula is withheld.

## Read-only incremental collection

```powershell
tm1-insight collect-process-metadata --process "Selected.Process" --output "new-metadata.json"
tm1-insight import-process-metadata --bundle "new-metadata.json" --database "offline-copy.duckdb"
```

Collection accepts 1..20 explicit names, reports progress and permits callback
cancellation between requests. The CLI uses a 15-second request timeout and a
5 MB bundle budget. It performs GETs for selected Process metadata,
the selected saved VIEW identity/type and source Cube dimension names; no cell
values, Preview, Execute, or server writes. New bundle files cannot overwrite
existing files. Raw bundles contain private Process code/metadata and belong
outside Git. DataSource credentials/queries are not included.

Import is a separate explicit offline operation. It rejects source mismatches
before changes, uses a transaction and touches only the additive metadata table.
Use an offline copy to preserve an immutable original. Model fingerprints and
parser/architecture revisions invalidate stale analysis caches.

The main collector now retains Variables/DataSource during new collection.
Existing skip-existing raw files are not silently rewritten: use the selected
metadata command for old Process records and saved VIEW metadata.

## Verification and current real-case boundary

`tests/test_data_row_lineage.py` covers A–I and the existing Cube-centric suite
remains required for J. It also tests actual installed TM1py properties,
Collector→Snapshot→Loader round trips, stale imports, mismatched view identities
and Cube order, CellPutS, metadata Section reassignment, API/export evidence and
metadata-only cache invalidation. Budgets: 20 selected Processes per incremental
bundle, 512 variables and 200000 metadata characters per Process, plus existing
worksheet/workflow node/source budgets. No new dependency or binary release.

The real acceptance Process's old raw JSON has no Variables and its persisted
DataSource is null. A configured read-only connection attempt failed before
metadata retrieval (`ConnectionError → ProtocolError → RemoteDisconnected`).
Therefore the real Data:42:3 write still has no proven row-value origin. The
implementation does not claim to have solved that real formula. Private local
before/after reports record the same write, exact missing metadata and the
read-only database/WAL integrity result.

Next: restore read-only connectivity, collect only the acceptance TI plus its
actual VIEW/layout, then confirm a real value write. Rule semantics and
Functional Architecture should consume these verified contracts only after
that boundary is proven.
