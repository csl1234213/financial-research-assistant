"""Contract checks for the canonical Docker deployment assets."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _compose() -> dict:
    compose_path = ROOT / "docker-compose.yml"
    return yaml.safe_load(compose_path.read_text(encoding="utf-8"))


class TestDockerComposeStructure:
    def test_canonical_compose_defines_the_current_service_topology(self):
        services = _compose()["services"]

        assert {"backend", "frontend", "agent-worker", "postgres", "redis", "chromadb"} <= set(services)

    def test_backend_waits_for_its_stateful_dependencies(self):
        backend = _compose()["services"]["backend"]

        assert {"postgres", "redis", "chromadb"} <= set(backend["depends_on"])
        assert "healthcheck" in backend

    def test_frontend_proxies_through_the_backend_service(self):
        frontend = _compose()["services"]["frontend"]

        assert frontend["build"]["dockerfile"] == "docker/Dockerfile.frontend"
        assert "backend" in frontend["depends_on"]

    def test_worker_reuses_the_api_image_and_waits_for_backend_bootstrap(self):
        services = _compose()["services"]
        backend = services["backend"]
        worker = services["agent-worker"]

        assert backend["build"]["dockerfile"] == "docker/Dockerfile.api"
        assert worker["image"] == backend["image"]
        assert "build" not in worker
        assert worker["command"] == ["python", "-m", "workers.agent_worker"]
        assert "backend" in worker["depends_on"]

    def test_worker_is_scalable_and_has_its_own_healthcheck(self):
        worker = _compose()["services"]["agent-worker"]

        assert "container_name" not in worker
        assert all(
            not entry.startswith("WORKER_ID=")
            for entry in worker["environment"]
        )
        assert worker["healthcheck"]["test"] == [
            "CMD",
            "python",
            "-m",
            "workers.agent_worker",
            "--healthcheck",
        ]

    def test_backend_and_worker_use_the_chromadb_service(self):
        services = _compose()["services"]
        backend = services["backend"]
        worker = services["agent-worker"]

        assert services["chromadb"]["image"] == "chromadb/chroma:1.5.9"
        assert "CHROMA_HOST=chromadb" in backend["environment"]
        assert "CHROMA_HOST=chromadb" in worker["environment"]
        assert all("chroma_local:" not in volume for volume in backend["volumes"])
        assert all("chroma_local:" not in volume for volume in worker["volumes"])

        requirements = (ROOT / "requirements" / "base.txt").read_text(encoding="utf-8")
        assert "chromadb==1.5.9" in requirements

    def test_worker_can_read_files_uploaded_by_the_api(self):
        services = _compose()["services"]
        expected_volume = "uploads_data:/app/storage/uploads"

        assert expected_volume in services["backend"]["volumes"]
        assert expected_volume in services["agent-worker"]["volumes"]

    def test_compose_does_not_embed_the_old_default_database_password(self):
        compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        assert "financial_secret" not in compose_text
        assert "POSTGRES_PASSWORD must be set in .env" in compose_text
        assert "REDIS_PASSWORD must be set in .env" in compose_text

    def test_stateful_services_are_bound_to_host_loopback(self):
        services = _compose()["services"]

        assert services["postgres"]["ports"] == ["127.0.0.1:5432:5432"]
        assert services["redis"]["ports"] == ["127.0.0.1:6379:6379"]
        assert services["chromadb"]["ports"] == ["127.0.0.1:8001:8000"]
        assert services["backend"]["ports"] == ["127.0.0.1:8000:8000"]

    def test_application_containers_force_production_mode(self):
        services = _compose()["services"]

        assert "APP_ENV=production" in services["backend"]["environment"]
        assert "APP_ENV=production" in services["agent-worker"]["environment"]

    def test_backend_uses_readiness_and_trusts_only_the_compose_proxy_path(self):
        backend = _compose()["services"]["backend"]

        assert backend["healthcheck"]["test"] == [
            "CMD",
            "curl",
            "-f",
            "http://localhost:8000/api/v1/ready",
        ]
        assert "TRUST_PROXY_HEADERS=true" in backend["environment"]

    def test_runtime_containers_share_a_cross_platform_huggingface_cache(self):
        compose = _compose()
        services = compose["services"]
        expected_mount = "huggingface_cache:/home/appuser/.cache/huggingface"

        assert expected_mount in services["backend"]["volumes"]
        assert expected_mount in services["agent-worker"]["volumes"]
        assert compose["volumes"]["huggingface_cache"]["name"] == (
            "financial_huggingface_cache"
        )
        assert "USERPROFILE" not in (ROOT / "docker-compose.yml").read_text(
            encoding="utf-8"
        )


class TestDockerfiles:
    def test_api_dockerfile_is_multi_stage_and_non_root(self):
        content = (ROOT / "docker" / "Dockerfile.api").read_text(encoding="utf-8")

        assert "AS builder" in content
        assert "AS runtime" in content
        assert "appuser" in content
        assert "HEALTHCHECK" in content

    def test_frontend_dockerfile_builds_react_and_serves_with_nginx(self):
        content = (ROOT / "docker" / "Dockerfile.frontend").read_text(encoding="utf-8")

        assert "npm ci" in content
        assert "npm run build" in content
        assert "nginx" in content.lower()


class TestDockerBuildContext:
    def test_environment_files_are_excluded_except_examples(self):
        patterns = {
            line.strip()
            for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        assert {".env*", "**/.env*"} <= patterns
        assert {"!.env.example", "!**/.env.example"} <= patterns

    def test_generated_state_and_local_databases_are_excluded(self):
        patterns = {
            line.strip()
            for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        assert {
            "chroma_db_test_*/",
            "*.db",
            "*.db-*",
            "cache/*",
            "!cache/*.py",
        } <= patterns


class TestRuntimeDependencies:
    def test_websockets_pin_is_compatible_with_langgraph_sdk(self):
        root_requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        api_requirements = (ROOT / "requirements" / "api.txt").read_text(encoding="utf-8")

        assert "-r requirements/dev.txt" in root_requirements
        assert "websockets==15.0.1" in api_requirements
        assert "websockets==16.0" not in api_requirements


class TestNginxConfig:
    def test_nginx_proxies_api_and_supports_spa_fallback(self):
        content = (ROOT / "docker" / "nginx.conf").read_text(encoding="utf-8")

        assert "resolver 127.0.0.11 valid=5s ipv6=off" in content
        assert "set $backend_origin backend:8000" in content
        assert "location /api/" in content
        assert "proxy_pass http://$backend_origin$request_uri" in content
        assert "proxy_set_header Authorization" not in content  # Preserve incoming auth header.
        assert "proxy_set_header Host $host" in content
        assert "location /assets/" in content
        assert _compose()["services"]["backend"]["healthcheck"]
        assert "try_files $uri $uri/ /index.html" in content
        assert "X-Content-Type-Options" in content
        assert "X-Frame-Options" in content

    def test_nginx_enforces_upload_and_edge_rate_limits(self):
        content = (ROOT / "docker" / "nginx.conf").read_text(encoding="utf-8")

        assert "client_max_body_size 50m" in content
        assert "limit_req_zone" in content
        assert "limit_req zone=api_per_ip" in content


class TestCanonicalDeploymentEntrypoints:
    def test_legacy_production_compose_is_a_thin_include(self):
        production_compose = (ROOT / "docker-compose.prod.yml").read_text(
            encoding="utf-8"
        )

        assert "path: docker-compose.yml" in production_compose
        assert "services:" not in production_compose

    def test_api_entrypoint_runs_the_canonical_fastapi_application(self):
        entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text(
            encoding="utf-8"
        )

        assert "api.main:app" in entrypoint
        assert "api.app:app" not in entrypoint


class TestEnvironmentContract:
    def test_environment_example_has_required_runtime_keys(self):
        content = (ROOT / ".env.example").read_text(encoding="utf-8")
        required = [
            "AUTH_SECRET_KEY",
            "DATABASE_URL",
            "POSTGRES_PASSWORD",
            "REDIS_PASSWORD",
            "REDIS_URL",
            "CHROMA_HOST",
            "CHROMA_SSL",
            "DEEPSEEK_API_KEY",
            "CORS_ORIGINS",
        ]

        for key in required:
            assert key in content, f"Missing key in .env.example: {key}"

    def test_environment_example_does_not_ship_a_provider_key(self):
        content = (ROOT / ".env.example").read_text(encoding="utf-8")

        assert "DEEPSEEK_API_KEY=your-deepseek-api-key" not in content


class TestCIWorkflow:
    def test_production_workflow_builds_current_api_and_react_images(self):
        content = (ROOT / ".github" / "workflows" / "production.yml").read_text(encoding="utf-8")

        assert "docker/Dockerfile.api" in content
        assert "docker/Dockerfile.frontend" in content
        assert "docker compose build backend frontend" in content
        assert "frontend-build" in content

    def test_ci_matches_the_production_python_and_compose_topology(self):
        content = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        assert 'python-version: "3.12"' in content
        assert 'python-version: "3.11"' not in content
        assert "pip install ruff==0.12.0" in content
        assert "docker compose build backend frontend" in content
        assert "docker compose build backend frontend agent-worker" not in content
        assert "docker compose run --rm --no-deps --entrypoint python backend" in content
        assert "docker compose run --rm --no-deps --entrypoint python agent-worker" in content

    def test_normal_ci_excludes_environment_sensitive_benchmark_suites(self):
        paths = [
            ROOT / ".github" / "workflows" / "ci.yml",
            ROOT / ".github" / "workflows" / "production.yml",
        ]
        expected_ignores = {
            "--ignore=tests/benchmark",
            "--ignore=tests/execution/test_execution_benchmark.py",
            "--ignore=tests/memory/test_memory_benchmark.py",
            "--ignore=tests/planning/test_complexity_benchmark.py",
        }

        for path in paths:
            content = path.read_text(encoding="utf-8")
            assert expected_ignores <= set(content.split())

    def test_release_workflow_publishes_only_after_immutable_images(self):
        production = (
            ROOT / ".github" / "workflows" / "production.yml"
        ).read_text(encoding="utf-8")
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

        assert "needs: [docker-push]" in production
        assert production.count("contents: write") == 1
        assert "gh release create" in production
        assert "--verify-tag" in production
        assert (
            'release_title="Financial AI Copilot V${base_version}"'
            in production
        )
        assert 'release_notes="docs/releases/v${base_version}.md"' in production
        assert "--latest" in production
        assert "permissions:\n  contents: read" in production
        assert "permissions:\n  contents: read" in ci

    def test_registry_publication_is_optional_without_repository_secrets(self):
        production = (
            ROOT / ".github" / "workflows" / "production.yml"
        ).read_text(encoding="utf-8")

        assert "Check Docker Hub publication configuration" in production
        assert 'echo "enabled=false" >> "$GITHUB_OUTPUT"' in production
        assert production.count(
            "if: steps.registry.outputs.enabled == 'true'"
        ) == 4
        assert "skipping registry publication" in production


class TestBackupScript:
    def test_backup_script_covers_postgres_and_chromadb(self):
        content = (ROOT / "scripts" / "backup_db.py").read_text(encoding="utf-8")

        assert "pg_dump" in content
        assert "backup_chromadb" in content
        assert "cleanup_old_backups" in content
