# D2-P1 — Chroma persistence contract repair and data preservation

## Scope and baseline

Pre-fix baseline: `6cc31e736baee6b696d4dac49bbb01d5a66d6251`.
Defect: `CHROMA_PERSISTENCE_PATH_MISMATCH`. The candidate changes only canonical
Compose's Chroma destination to `/data`, removes the obsolete `PERSIST_DIRECTORY`
setting, and adds a dedicated deployment regression plus this report. Application
Python/frontend, client, embedding, retrieval, FACT, Provider and collections are
not changed. No production Chroma replacement is authorized or performed here.

The new commit identity, final preflight and Jev decisions are recorded after
acceptance in the external `d2-p1/closure-receipt.json`; this document cannot
embed its own future Git commit hash. Do not treat the pre-fix SHA as the final
release baseline after this fix is committed.

## Authority and current data

Current original container `financial-chromadb`:
`57286c67ad8ed9efbc59484e5c30c6655f78288e9419a6e6f946b3002b8364de`.
Created `2026-09-06T05:36:12.090846105Z`, restart policy `unless-stopped`, network
`financial_network`. Image tag `chromadb/chroma:1.5.9`; exact local image ID:
`sha256:1e0b73a187a28757c572acba508c46f48c9e8b0acaf5c20e6d95cdedce1acdf6`.
The runtime API reports version `1.0.0`; this differs from the tag and is recorded,
not silently represented as a verified binary version. Tests use this exact same
image ID and the observed runtime configuration.

Actual command: `dumb-init -- chroma run /config.yaml`. The file says
`persist_path: "/data"`. The running server opens HNSW index files under `/data`.
API exposes one default-tenant/default-database collection, 2239 records. Its UUID
and record count match the complete cold `/data` SQLite metadata. Index segment
UUID matches the disk directory. This is not a size-based authority inference.

The image's [versioned Rust Dockerfile](https://github.com/chroma-core/chroma/blob/1.5.9/rust/Dockerfile)
loads the [single-node Docker config](https://github.com/chroma-core/chroma/blob/1.5.9/rust/frontend/sample_configs/docker_single_node.yaml).
The [loader](https://github.com/chroma-core/chroma/blob/1.5.9/rust/frontend/src/config.rs)
merges YAML with `CHROMA_`-prefixed settings, not legacy `PERSIST_DIRECTORY`.
The repair uses official `/data` default + `/data` mount, no env override guess.

`ACTIVE_PERSIST_PATH=/data`.
`ACTIVE_DATA_LOCATION=ACTIVE_DATA_IN_CONTAINER_LAYER_DATA`.
`EXISTING_DATA_AUTHORITY=PROVEN` through config + process file handles + API/DB
identity/count correspondence. `/data` has no mount in the original container.
The original volume `financial_chroma_prod` is still mounted read-write at
`/chroma/chroma`, containing one 167,936-byte SQLite file, zero collections and
zero segments. It is not the active dataset and is preserved separately.

## Cold backup and integrity

Backup root:
`<private-acceptance-artifacts>/rc1-r4\d2-p1\backup-20261003T114956Z`.
UTC start `2026-10-03T11:49:56.399928+00:00`; stopped source verified
`2026-10-03T11:49:57.273443+00:00`; backup verified
`2026-10-03T11:49:59.568530+00:00`. The exact same original container resumed
at `2026-10-03T11:50:00.383967+00:00`.

Complete active `/data`: 6 files, 38,731,818 bytes. Complete legacy directory:
1 file, 167,936 bytes. Independent stopped-source archive SHA256/size per file
matches both local copies; no SQLite-only copy was substituted. Both databases
pass immutable read-only `PRAGMA integrity_check` with `ok`. Backup copies are
never opened read-write; their SQLite/index data stays unchanged.

Manifest: `<backup root>/sha256-manifest.json`; source IDs/paths, individual
hashes/sizes/mtimes, database metadata/count evidence and method are preserved in
`d2-p1/backup-receipt.json`. Original container, writable layer and named volume
were not removed, recreated, moved or overwritten. No collection was cleared or
re-embedded. A brief Chroma-only stop was used for consistency, not a whole-stack
shutdown; ingestion clients may have experienced transient unavailability then.

## Isolated migration and replacement proof

The complete active backup was restored into a NEW isolated volume:
`financial-rc1-d2p1-3529037ea8-preserved`, at its root corresponding to `/data`.
All six restored file hashes matched before startup. Its isolated service API
returned the same collection UUID and 2239 records. Restored verification
container `f01a983dd0d775913a2a184ae2621aba7bece870c597cbcb6dad99bb1e6016dc`
is retained stopped; no production container uses this target volume yet.

Separate deterministic persistence test volume:
`financial-rc1-d2p1-3529037ea8-replacement`. Three explicit 2-dimensional vectors,
documents and metadata were inserted; exact get/count/nearest-query passed.
The old TEST container
`f9f249bd0da991b7d1e9ee2d555f71105c387851c0a8f4c609d7b8359b798bae`
was stopped and actually removed. A different TEST container
`1adb65c2b1ceb07a609e469c40a2624d1c385aaa208a07dab1e4be4ffbb91c42`
was created with the same image and named volume. All three records, exact
embeddings/documents/metadata, nearest IDs and distances survived. Record
fingerprint before/after:
`ab8c40f019334ee7424893c169dfdcd60a254bad07218b6869644fc61d87593e`.
`CONTAINER_REPLACEMENT_PERSISTENCE=PASS`; restart-only is not the proof.

Both services use a fresh dedicated bridge network
`financial-rc1-d2p1-3529037ea8-network` with localhost-only ports 53105/53106.
All isolated resources are labelled `financial.scope=d2-p1`; production resources
are not reused. Accepted proof is `isolated-persistence-receipt.json`.
First isolated attempt used an internal bridge: container-local heartbeat 200,
host publication timeout; restore hashes passed but replacement was NOT_RUN.
That environment/harness attempt is preserved as `isolated-attempt-1.json`, not
counted as PASS. Its volumes and stopped container remain untouched.

## Regression and candidate boundary

New Chroma regression first produced one expected failure on the original wrong
mount, then passed after the minimal change. Relevant Chroma + canonical Compose
structure tests: 16 PASS. An exploratory broader deployment run had 32 PASS and
one existing Nginx source-string assertion failure. The identical failure was
reproduced on the unmodified pre-fix checkout; actual Nginx uses a DNS-resolved
variable backend origin. No Nginx behavior/test was changed or included here.
That historical failure is not falsely reported as a full deployment-suite PASS.

H0 qualified runtime/config gates are reused. Candidate support requires a
three-file hash manifest, unchanged 495 runtime hashes, exact pre-fix ancestry,
no hidden untracked dependencies, and full parsed YAML equality except the
approved mount/env changes. It is not a blanket dirty-worktree bypass. Full
static preflight runs from baseline gate, not from the previous failed gate.
Post-commit clean-history validation is recorded separately. Harness tooling
remains separate from this three-file product fix; no historical untracked H0 or
Answer/retrieval code is absorbed into this commit.

## Migration plan and stop boundary

Do NOT run existing production `compose up` blindly after this edit: canonical
production volume naming is retained, and that old volume does not contain the
active 2239-record dataset. This phase does not connect the preserved target to
production. For subsequent isolated RC deployment, create its separately named
RC target and restore the verified full snapshot before starting Chroma, or
explicitly qualify using the preserved isolated target. Never merge it with the
legacy volume. No overwrite/delete of either original location is authorized.

The source was resumed after cold backup. The snapshot is valid as of its UTC
timestamp; subsequent production writes are not included. Any later production
cutover requires a new write-quiesced snapshot/delta plan and verification. This
receipt is not authorization to discard later changes or the original container.

Provider calls this phase = 0; global budget remains 4/4 exhausted. No formal
Docker RC build/up or frontend UAT occurred. Test containers/volumes are the
explicitly authorized persistence test only. `LOCAL_UAT_READY=false` even after
static acceptance. Full 419 application suite is not repeated because all 495
runtime hashes are unchanged. Build readiness is granted only by the final
candidate/history static receipts + independent Jev PASS + safe commit receipt.
Then STOP and wait for the next authorized RC build phase.
