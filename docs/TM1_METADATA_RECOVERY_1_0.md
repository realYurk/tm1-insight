# TM1 Read-Only Metadata Recovery 1.0

This slice repairs connection diagnostics and metadata persistence. It does not
change TI parsing, Calculation DAGs, value-dependency rules, Rule/Feeder,
Workbench, code generation or architecture semantics. Previous uncommitted
Data Row Lineage work remains intact.

## Failure boundary and what is actually known

The installed TM1py is 2.4.1. Its constructor starts a Basic/CAM session using
GET `Configuration/ProductVersion/$value`. The real acceptance attempt fails
here with `ConnectionError → ProtocolError → RemoteDisconnected`, before any
Process metadata request. An unauthenticated version GET also fails. TCP can
connect; a TLS-only probe has not obtained a certificate, and a later bounded
probe times out. No successful REST response was received.

Consequently neither invalid credentials, incorrect SSL, SSO incompatibility,
certificate trust, a bad Process query, nor an incorrect server port is proven.
The configured endpoint's application-layer REST access is blocked or
unavailable from this environment. Server configuration/network policy evidence
is needed to distinguish the exact cause. There is no automatic protocol,
port, authentication or proxy change.

Windows has proxy settings, but requests applies the system's existing bypass
rules for this address and selects no effective proxy. This is observed default
behavior, not a new bypass introduced by the application.

## Safe connection behavior

`diagnose-tm1-metadata` stages are CONFIG → TCP → TLS (or a no-auth TLS protocol
probe on the configured port) → existing proxy selection → unauthenticated REST
version GET. A successful diagnostic command exit means a report was produced,
not that its stages succeeded. Inspect the stage statuses/categories.

Diagnostics preserve proxy rules, disable redirects and explicit/implicit
`.netrc` authentication, and never print URLs, credentials, headers, cookies,
tokens, raw response bodies or exception messages. Error categories distinguish
DNS/network, timeout, TLS/certificate, proxy, 401 authentication, 403 permission,
404 missing resource, incompatible request/API and response parsing.

`connect_metadata()` reuses TM1py with configured host/REST port, HTTP/HTTPS and
Basic/CAM settings. It explicitly verifies TLS, accepts a trusted CA file through
`TM1_CA_BUNDLE` (or existing requests CA environment variables), and rejects the
string `False`. It disables async execution, server cancellation actions and
automatic reconnect/retries. Each request has a bounded timeout. No attempt is
made to fall back to unverified TLS or a different authentication scheme.

TM1py's normal context manager POSTs `ActiveSession/tm1.Close` at exit. Recovery
instead closes only its local HTTP session; it does not call server logout.
Authenticated server sessions expire under existing server policy. A transport
test using the real TM1py class proves that a complete synthetic collection
sends four GETs and no POST/PUT/PATCH/DELETE, including session initialization.

## Minimal requests and compatibility fixes

After the session/version GET, only these selected resources are queried:

1. `Processes('selected')?$select=Name,DataSource/Type,DataSource/dataSourceNameForServer,DataSource/view,Variables,Parameters,PrologProcedure,MetadataProcedure,DataProcedure,EpilogProcedure`
2. The selected stored `Cubes('source')/Views('view')?$select=Name`, preserving
   the actual derived NativeView/MDXView type when returned.
3. The source Cube name and ordered Dimension names, with no cell values.

The four Process sections are needed to verify identity against the local
snapshot, not to execute them. DataSource credentials and queries are excluded.
TM1py 2.4.1 exposes `_tm1_rest`, not the previous `_rest` assumption. Recovery
uses the actual RestService GET interface and explicitly selects datasource
subfields; the narrow legacy injected-client adapter remains supported.

Cancellation callbacks run before connecting, between requests, after responses
and during local import. KeyboardInterrupt propagates. Request timeouts bound a
currently blocked read; no server-side cancellation operation is sent. There
are zero automatic retries. Limits remain 1–20 selected Processes, 512 Variables
per Process, a 5 MB bundle and a 1–30 second CLI timeout.

## Persistence and recovery

Collection first validates names, JSON shape and integer Position/StartByte/
EndByte fields. Missing Variables and failed View reads are explicit statuses,
not invented defaults. Missing View metadata can preserve a successfully read
Process in the new bundle, but cannot prove a View row layout.

A complete collection writes a new canonical immutable Snapshot through the
existing Collector mapper/SnapshotStore, then publishes a new bundle from a
flushed temporary file. Existing bundle files and historical Snapshots are never
overwritten. Failed collection publishes no partial bundle.

Import checks all selected source hashes and rechecks within the transaction.
It adds only `process_source_metadata`, leaving all Process sections and normal
data tables untouched. The CLI writes a metadata-only backup before changes.
Mid-import failures roll back the transaction; missing Variables/View metadata
cannot silently downgrade an existing complete metadata record. Reimporting a
bundle preserves the same logical record, not duplicate rows.

`restore-process-metadata` can restore the selected prior metadata or remove
newly added records, while rejecting a changed Process source. It does not
restore/change business values or source code. Old snapshots/databases without
these optional fields remain readable by the unchanged lineage engine.

## Safe commands in an authorized enterprise environment

Use the project's existing approved connection configuration locally. Do not
send passwords or full company datasets to an assistant. A server administrator
must confirm HTTPPortNumber, protocol, Basic/CAM mode and the approved route if
the version request cannot succeed. For HTTPS, install/configure the approved
CA certificate instead of disabling validation.

```powershell
# Run from this repository, with its existing Python/TM1py environment.
$env:PYTHONPATH = 'src'
New-Item -ItemType Directory -Path 'C:\TM1_Metadata' -Force | Out-Null

.\.venv\Scripts\python.exe -m tm1_insight.cli diagnose-tm1-metadata `
  --timeout 5 --output 'C:\TM1_Metadata\diagnostics.json'

.\.venv\Scripts\python.exe -m tm1_insight.cli collect-process-metadata `
  --process 'Selected.Process' --timeout 15 `
  --output 'C:\TM1_Metadata\selected-metadata.json'

# Select a matching offline model copy explicitly.
.\.venv\Scripts\python.exe -m tm1_insight.cli import-process-metadata `
  --bundle 'C:\TM1_Metadata\selected-metadata.json' `
  --database 'C:\TM1_Metadata\model-copy.duckdb'

# If needed, use the exact backup filename printed by import.
.\.venv\Scripts\python.exe -m tm1_insight.cli restore-process-metadata `
  --backup 'C:\TM1_Metadata\model-copy.duckdb.metadata-backup-<id>.json' `
  --database 'C:\TM1_Metadata\model-copy.duckdb'
```

Replace Selected.Process with the fixed acceptance name from the task. Keep the
selected bundle/snapshots/backup private. Only the selected Process definition,
Variables and necessary View/Cube structure are required; no numerical Cube
export is needed. A locally authorized raw metadata export can be represented
in the same `process-metadata-1` bundle contract and imported without any new
semantic assumptions. No unsupported `.pro` or native View binary format is
claimed to have been decoded.

## Real acceptance status

The real connection is not restored. The existing selected raw JSON has neither
Variables nor DataSource; the selected DuckDB lacks the additive metadata table.
No matching `.pro` export or relevant Snapshot payload was found within the
configured bounded local-material search. No real recovery bundle was created,
and no real metadata was imported into DuckDB.

Reanalysis still finds 12 ACT target writes and the same Data:42:3 vValue write,
with no new proven row-value origin. Missing evidence is the actual Variables
definition and the actual bound View/layout/value-column relationship. Existing
Prolog source-Cube binding is retained independently. Original DB and WAL
integrity checks pass. This environment block is not represented as a successful
real formula or replaced by Mock results.

`tests/test_metadata_recovery.py` covers failure classification/redaction,
TLS/proxy behavior, Process permissions/missing variables, actual TM1py GET-only
transport, Snapshot→DuckDB→binding, atomic files, idempotence, downgrade guards,
mid-write rollback, executable CLI backup/restore and old contracts. Full
regression remains required. Portable binaries are not rebuilt or published.

After REST access and metadata are available, existing semantic gaps may still
include a dynamically generated View identity/layout, MDX rowsets/properties,
cross-helper parameter propagation and value-column mapping. These belong to a
separate semantic task; no rules are loosened in this recovery slice.
