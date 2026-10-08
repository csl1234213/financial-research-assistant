# Linux Production Deployment

This runbook prepares an Ubuntu VPS for `rag.agentbuildlab.com`. It does not
contain credentials and never deletes application volumes.

## Prerequisites

- Ubuntu 22.04+ with Docker Engine and the Compose plugin
- DNS access for `agentbuildlab.com`
- A public IPv4 address and firewall access
- A production `.env` created on the VPS (never committed)

Create the required secrets locally on the VPS, for example with
`openssl rand -hex 32` and `openssl rand -base64 48`. Set `AUTH_SECRET_KEY`,
`POSTGRES_PASSWORD`, `REDIS_PASSWORD`, and the provider credentials required
for the demo in `.env`. Use only public or redacted financial PDFs.

## Firewall and DNS

Allow `22/tcp`, `80/tcp`, and `443/tcp`; do not expose PostgreSQL, Redis,
ChromaDB, the backend port, or the worker. Create an A record:

```
rag.agentbuildlab.com -> <VPS_PUBLIC_IPV4>
```

Wait for DNS propagation before starting Caddy; ACME can only issue a
certificate after the hostname resolves to this server.

## Deploy

```bash
export PUBLIC_DOMAIN=rag.agentbuildlab.com
export ACME_EMAIL=ops@example.com
docker compose -f docker-compose.yml -f docker-compose.linux.yml config -q
./scripts/deploy_linux.sh
```

The Linux overlay exposes only Caddy on ports 80/443. Caddy terminates TLS
and proxies to the internal frontend, which proxies `/api/` to FastAPI.
PostgreSQL, Redis, ChromaDB, uploads, memory, logs, and Caddy state use named
Docker volumes and survive container restarts.

## Verify and recover

```bash
python scripts/smoke_online.py --base-url https://rag.agentbuildlab.com
docker compose -f docker-compose.yml -f docker-compose.linux.yml ps
docker compose -f docker-compose.yml -f docker-compose.linux.yml restart
python scripts/smoke_online.py --base-url https://rag.agentbuildlab.com
```

Use the P0.2 backup/restore scripts for database and uploads recovery. Chroma
is derived data and can be rebuilt from PostgreSQL metadata and uploaded PDFs.
Never use `down -v`, volume prune, or an in-place restore on the live stack.

## Post-deployment smoke plan

In an isolated browser session verify home page, login, public PDF upload,
indexing completion, single- and multi-document RAG, citations, refresh, and
restart persistence. Do not use real user data, private documents, or personal
API keys in the public demo. Live LLM and citation checks are intentionally not
run by the credential-free smoke script.
