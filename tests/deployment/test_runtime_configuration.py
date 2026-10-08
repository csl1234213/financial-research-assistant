"""Focused tests for Docker / entrypoint runtime configuration."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_worker_compose_command_is_an_exec_form_list() -> None:
    compose_path = ROOT / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    assert compose["services"]["agent-worker"]["command"] == [
        "python",
        "-m",
        "workers.agent_worker",
    ]


def test_backend_entrypoint_forwards_supplied_commands() -> None:
    entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")

    assert 'if [ "$#" -gt 0 ]; then' in entrypoint
    assert 'exec "$@"' in entrypoint


def test_backend_entrypoint_rejects_placeholder_infrastructure_secrets_in_production() -> None:
    entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")

    assert 'require_production_secret "POSTGRES_PASSWORD"' in entrypoint
    assert 'require_production_secret "REDIS_PASSWORD"' in entrypoint


def test_production_entrypoint_uses_migrations_before_reference_data_seed() -> None:
    entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")

    migration_position = entrypoint.index("alembic upgrade head")
    seed_position = entrypoint.index(
        "from storage.database import seed_defaults; seed_defaults()"
    )

    assert migration_position < seed_position
    assert "from storage.database import init_db" not in entrypoint
