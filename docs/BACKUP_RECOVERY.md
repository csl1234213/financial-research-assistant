# Backup and Recovery Runbook

## V8.1 unified bundle and derived-data reindex

The repeatable bundle command is:

```powershell
python scripts/backup.py --output-dir D:\\financial-rag-backups\\p0.2-<id> --git-commit (git rev-parse HEAD)
python scripts/verify_backup.py D:\\financial-rag-backups\\p0.2-<id>
```

The bundle contains PostgreSQL `pg_dump -Fc`, an uploads archive with
`uploads_manifest.json`, a Chroma snapshot, and a secret-free
`backup_manifest.json`. PostgreSQL and uploads are authoritative; Chroma is
derived and can be rebuilt from restored PDFs.

For an isolated Chroma container, re-index restored PDFs without touching the
production database or volume:

```powershell
python scripts/reindex_chroma.py /app/storage/uploads
```

In the local drill, five restored PDFs produced 345 queryable chunks and a
similarity search returned `Tesla_sample.pdf`. This completed the Chroma
fallback verification. KMS/secret-manager encryption and off-site transfer
remain production configuration requirements; no live remote upload was run.

### LLM provider credential boundary

The running stack uses `LLM_CREDENTIAL_ENCRYPTION_KEYS` and the runtime file
`/app/storage/memory/.llm-credential-key` from the `agent_memory` volume to
decrypt provider credentials. These values are intentionally excluded from
the PostgreSQL/uploads/Chroma bundle. Disaster recovery must inject them from
an external Secret Manager before claiming a restored `/api/v1/chat` report.
Without that controlled injection, health, authentication, and retrieval can
be verified, but a real LLM response must remain unverified.

This runbook defines the minimum supported disaster-recovery loop for the
canonical repository-root `docker-compose.yml` stack. It covers PostgreSQL and
the remote Chroma service's named volume without requiring a cloud-specific
backup product.

## Recovery objectives

The initial operational objectives are:

| Data set | Backup policy | RPO objective | RTO objective |
| --- | --- | --- | --- |
| PostgreSQL | Daily coordinated logical dump | 24 hours | 2 hours |
| Chroma `financial_chroma_data` | Daily offline volume snapshot | 24 hours | 2 hours |

These are objectives, not guarantees. Measure actual dump, transfer, restore,
index-startup, and verification times during each recovery drill. Tighten the
objectives only after measured evidence supports the change.

Keep at least seven daily recovery sets. Copy each complete set (artifacts and
their `.manifest.json` sidecars) to access-controlled storage on a different
host or failure domain. The scripts provide integrity checks, not encryption
or authenticity; apply encryption and immutable retention in the storage
system that receives the backups.

## What is and is not protected

- PostgreSQL logical dumps protect relational application, billing, task, and
  checkpoint records stored in PostgreSQL.
- The Chroma snapshot protects the canonical `financial_chroma_data` vector
  volume.
- Redis is treated as cache/queue state, not a system of record. In-flight work
  may need to be resubmitted after recovery.
- `financial_uploads` and `financial_agent_memory` are separate named volumes
  and are not covered by this minimum database procedure. Back them up through
  the deployment platform's file/volume snapshot facility when those files are
  required for disaster recovery.

## Backup artifact contract

Every successful script-generated artifact has a sidecar:

```text
backup_financial_rag_YYYYMMDD_HHMMSS.dump
backup_financial_rag_YYYYMMDD_HHMMSS.dump.manifest.json
```

The manifest records:

- schema version and UTC creation time;
- backup type and format;
- non-secret source metadata;
- artifact size;
- SHA-256 checksum;
- restore tool metadata.

Artifacts are first written with a `.partial` name and published only after
the external command succeeds. Never restore an artifact without its matching
manifest. Keep the artifact and sidecar together when copying or expiring a
recovery set.

## Coordinated backup procedure

Use an absolute backup directory outside the Git checkout. The following
examples use `/srv/financial-backups/current`; on Windows, a path such as
`D:\financial-backups\current` is appropriate.

1. Verify sufficient free space and record the current application version.
2. Quiesce API and retrieval writers. PostgreSQL remains available so
   `pg_dump` can run:

   ```bash
   docker compose stop backend agent-worker chromadb
   ```

3. Create a PostgreSQL custom-format logical dump through the existing
   PostgreSQL container. This does not require host-installed PostgreSQL
   tools:

   ```bash
   python scripts/backup_db.py \
     --compose-service postgres \
     --db-name financial_rag \
     --db-user financial \
     --postgres-format custom \
     --skip-local-chroma \
     --output-dir /srv/financial-backups/current
   ```

   `POSTGRES_DB` and `POSTGRES_USER` can be passed explicitly when the
   deployment does not use the defaults. A direct database URL and
   host-installed `pg_dump` are also supported by replacing the Compose
   arguments with `--db-url postgresql://...`.

4. Snapshot Chroma through the restricted, network-disabled one-shot Compose
   helper. The script refuses to continue if `backend`, `agent-worker`, or
   `chromadb` is still running, if any other running container mounts the
   target volume, or if the volume is missing or empty:

   ```bash
   python scripts/chroma_volume.py backup \
     --output-dir /srv/financial-backups/current
   ```

   The helper definition is
   `scripts/docker-compose.maintenance.yml`; it mounts
   `financial_chroma_data` read-only for backup. Do not archive a live Chroma
   volume directly from Docker's internal volume directory.

5. Restart and verify the stack:

   ```bash
   docker compose up -d
   docker compose ps
   curl --fail http://localhost:8000/api/v1/health
   ```

6. Copy both artifacts and both manifests off-host. Alert if any expected file
   is missing, has zero bytes, or cannot be copied.

The service pause bounds cross-store drift: while writers are stopped, the
PostgreSQL dump and Chroma archive form one coordinated recovery set. Name or
catalog the four files together with the application version and deployment
identifier.

## PostgreSQL restore

Restore into an isolated staging database first whenever possible. Ensure the
target PostgreSQL major version is compatible with the dump producer and use
an application image/migration level compatible with the recovery set.

1. Start only PostgreSQL and keep application writers stopped:

   ```bash
   docker compose up -d postgres
   docker compose stop backend agent-worker
   ```

2. Run a non-mutating preflight. `--confirm-target` must exactly match the
   target database name:

   ```bash
   python scripts/restore_db.py \
     --artifact /srv/financial-backups/current/backup_financial_rag_TIMESTAMP.dump \
     --compose-service postgres \
     --db-name financial_rag \
     --db-user financial \
     --confirm-target financial_rag \
     --dry-run
   ```

   The preflight validates manifest schema, filename, size, SHA-256 checksum,
   format, confirmation, and restore command selection. It executes neither
   `pg_restore` nor `psql`.

3. Restore. For a custom dump into an existing database, `--clean` explicitly
   requests `pg_restore --clean --if-exists`. Omit it for a newly created,
   empty target:

   ```bash
   python scripts/restore_db.py \
     --artifact /srv/financial-backups/current/backup_financial_rag_TIMESTAMP.dump \
     --compose-service postgres \
     --db-name financial_rag \
     --db-user financial \
     --confirm-target financial_rag \
     --clean
   ```

   Custom dumps use `pg_restore`; plain `.sql` and `.sql.gz` backups use
   `psql`. Both paths stop on the first SQL error and use a single transaction.
   The restore process never runs before checksum validation.

4. Inspect PostgreSQL logs and perform the verification checklist below before
   enabling writers.

## Chroma volume restore

Chroma restore replaces the current contents of `financial_chroma_data`.
Create a fresh backup of the current volume first if rollback may be needed.

1. Stop all potential Chroma writers:

   ```bash
   docker compose stop backend agent-worker chromadb
   ```

2. Run the non-mutating preflight:

   ```bash
   python scripts/chroma_volume.py restore \
     --artifact /srv/financial-backups/current/backup_chroma_volume_TIMESTAMP.tar.gz \
     --confirm-volume financial_chroma_data \
     --dry-run
   ```

   The preflight verifies the sidecar checksum, manifest target, archive type,
   every archive member path/type, and stopped-service state.

3. Perform the restore using the exact same command without `--dry-run`:

   ```bash
   python scripts/chroma_volume.py restore \
     --artifact /srv/financial-backups/current/backup_chroma_volume_TIMESTAMP.tar.gz \
     --confirm-volume financial_chroma_data
   ```

   A network-disabled one-shot Alpine container mounts the backup directory
   read-only, validates the archive again, clears the target volume, and
   extracts the verified snapshot. On a fresh host, Compose creates the named
   volume for the restore helper.

4. Start Chroma first, wait for it to become healthy, then start the
   application:

   ```bash
   docker compose up -d chromadb
   docker compose ps chromadb
   docker compose up -d backend agent-worker frontend
   ```

## Restore verification checklist

Do not declare recovery complete based only on successful command exit codes.
Record evidence for all applicable checks:

1. Both restore preflights passed and checksum values match the archived
   manifests.
2. PostgreSQL accepts connections, expected schemas/tables exist, and a
   representative tenant's row counts match the recovery-set inventory.
3. Chroma reports healthy and expected collection/count metadata is present.
4. `GET /api/v1/health` and readiness checks pass without dependency
   degradation.
5. Authentication and tenant isolation smoke tests pass.
6. A known financial RAG query returns the expected tenant-scoped source, and
   the deterministic retrieval evaluation gate passes.
7. Worker startup, queue processing, and a harmless asynchronous task pass.
8. Backup/restore start and end times, data sizes, failures, and measured RPO
   and RTO are added to the drill record.

## Recovery drill cadence

Run an isolated restore drill at least quarterly and after material PostgreSQL,
Chroma, migration, or backup-script changes. Never aim a drill at production.

The drill should:

1. select a real off-host recovery set without altering it;
2. provision isolated Docker volumes and non-production credentials;
3. execute both dry-run preflights;
4. restore PostgreSQL and Chroma;
5. complete the verification checklist;
6. destroy only the explicitly identified drill environment;
7. document measured RPO/RTO and corrective actions.

CI tests intentionally mock Docker and PostgreSQL subprocesses. They prove
manifest/confirmation/fail-closed behavior, but they do not replace the
quarterly restore drill.
# P0.2 unified backup bundle (V8.1)

The repeatable operator entry point is kept outside the repository output
directory (for example `D:\\financial-rag-backups\\p0.2-<id>`):

```powershell
docker compose stop backend agent-worker chromadb
python scripts/backup.py --output-dir D:\\financial-rag-backups\\p0.2-<id> --git-commit (git rev-parse HEAD)
docker compose up -d backend agent-worker chromadb
python scripts/verify_backup.py D:\\financial-rag-backups\\p0.2-<id>
```

The bundle contains a PostgreSQL `pg_dump -Fc`, an uploads tar archive plus
`uploads_manifest.json`, a Chroma volume snapshot, and a secret-free
`backup_manifest.json`. The scripts refuse to overwrite an existing output
directory and reject unsafe archive paths. Backup output is not stored in Git.

## Data authority matrix

| Data | System of record |
| --- | --- |
| users, tenants, documents, tasks, usage, subscriptions, provider metadata, sessions/checkpoints | PostgreSQL |
| uploaded PDFs | `financial_uploads` volume |
| embeddings and chunks | Chroma (`financial_chroma_prod`), derived from PostgreSQL + PDFs |
| queue state, cache, rate limiting | Redis (non-authoritative) |

Loss of Redis does not require restoring core business data; queued work and
cache entries may be rebuilt. PostgreSQL and uploads are authoritative.

## Isolated restore drill

Never restore into canonical volumes. Use a separately named PostgreSQL volume
and a separately named Chroma volume/container, then validate the dump with:

```powershell
python scripts/restore.py D:\\financial-rag-backups\\p0.2-<id> --target fra-p02-postgres-restore
```

The production volume names are explicitly rejected by `restore.py`. A real
drill must verify database rows, upload SHA-256 values, and a Chroma query from
the isolated environment. In this environment the captured Chroma SQLite
volume started successfully but did not contain the live collection records;
therefore Chroma is treated as rebuildable derived data and the release gate
remains **PARTIAL** until an isolated re-index from restored PostgreSQL and
uploads is completed.

## Encryption, off-site, retention, and RPO/RTO

Artifacts must be encrypted before leaving the host using an external KMS or
secret-manager controlled key. No key is written to code, manifests, logs, or
Git. KMS integration is a production configuration requirement; no remote
upload was performed in the local drill (`OFFSITE_UPLOAD: NOT_RUN`).

Retention should be configured by the operator with an explicit
`BACKUP_RETENTION_DAYS` policy and must only remove recognized backup bundles.
For a daily cadence the design target is potential RPO <= 24 hours; this is not
an SLA. The measured PostgreSQL/uploads/Chroma artifact creation duration for
the local drill is recorded in `backup_manifest.json`; restore duration is an
experiment result, not a commercial RTO.

## Failure behavior

`verify_backup.py` fails closed for a missing artifact, modified checksum,
missing manifest, unsafe archive member, or invalid Chroma archive. Restore
helpers never target canonical production volumes. Test encryption with the
external encryption tool before scheduling off-site transfer.
