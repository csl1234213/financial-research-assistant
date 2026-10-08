"""
Sprint 9.3 Phase 1 — Full End-to-End Validation v4
"""
import io
import subprocess
import time
import uuid

import fitz
import pytest
import requests

pytestmark = pytest.mark.live

BASE = "http://localhost:8000/api/v1"
RESULTS = []

def _e2e_test(name, fn):
    try:
        fn()
        RESULTS.append((name, "PASS", ""))
    except Exception as e:
        RESULTS.append((name, "FAIL", str(e)[:120]))

def report():
    print("\n" + "=" * 70)
    print("SPRINT 9.3 PHASE 1 — E2E VALIDATION REPORT")
    print("=" * 70)
    print(f"\n{'Test Case':<45} {'Result':<8} {'Issue'}")
    print("-" * 70)
    for name, result, issue in RESULTS:
        print(f"{name:<45} {result:<8} {issue}")
    passed = sum(1 for _, r, _ in RESULTS if r == "PASS")
    total = len(RESULTS)
    print("-" * 70)
    print(f"Total: {passed}/{total} passed")
    score = int(passed / total * 100) if total else 0
    print(f"Production Readiness Score: {score}%")

# Unique emails
uid = uuid.uuid4().hex[:8]
EMAIL_A = f"test_a_{uid}@example.com"
EMAIL_B = f"test_b_{uid}@example.com"

# ============================================================
# 1. Application Health
# ============================================================
@pytest.mark.e2e
def test_health():
    resp = requests.get(f"{BASE}/health")
    assert resp.status_code == 200, f"Status: {resp.status_code}"
    data = resp.json()
    assert data["status"] == "ok", f"Expected 'ok', got: {data['status']}"
    assert data["service"] == "Financial Research Copilot"

if __name__ == "__main__":
    _e2e_test("1.1 Health API", test_health)

# ============================================================
# 2. Authentication Flow
# ============================================================
tokens = {}

@pytest.mark.e2e
def test_register():
    resp = requests.post(f"{BASE}/auth/register", json={
        "email": EMAIL_A,
        "password": "Test@123456",
        "name": "Test User A"
    })
    assert resp.status_code == 201, f"Register: {resp.status_code} {resp.text}"
    data = resp.json()
    assert "token" in data, "No token"
    assert data["email"] == EMAIL_A
    tokens["user_a"] = data["token"]

@pytest.mark.e2e
def test_me():
    resp = requests.get(f"{BASE}/auth/me", headers={"Authorization": f"Bearer {tokens['user_a']}"})
    assert resp.status_code == 200, f"Me: {resp.status_code} {resp.text}"
    data = resp.json()
    assert data["email"] == EMAIL_A
    assert "tenant" in data, "No tenant"
    assert "id" in data["tenant"], "No tenant id"

@pytest.mark.e2e
def test_login():
    resp = requests.post(f"{BASE}/auth/login", json={
        "email": EMAIL_A,
        "password": "Test@123456"
    })
    assert resp.status_code == 200, f"Login: {resp.status_code} {resp.text}"
    data = resp.json()
    token = data.get("access_token") or data.get("token")
    assert token, f"No token: {list(data.keys())}"
    assert data.get("token_type") == "bearer"
    tokens["user_a"] = token

# ============================================================
# 3. Upload & Task Processing
# ============================================================
task_ids = {}


def _valid_pdf(text: str) -> bytes:
    """Create a minimal one-page, text-bearing PDF for the happy-path E2E."""
    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), text)
        return document.tobytes()
    finally:
        document.close()

@pytest.mark.e2e
def test_upload_pdf():
    pdf_content = _valid_pdf("Tesla financial report. Revenue: 82.4 billion USD.")
    files = {"file": ("tesla_report.pdf", io.BytesIO(pdf_content), "application/pdf")}
    headers = {"Authorization": f"Bearer {tokens['user_a']}"}
    resp = requests.post(f"{BASE}/upload", files=files, headers=headers)
    assert resp.status_code == 200, f"Upload: {resp.status_code} {resp.text}"
    data = resp.json()
    assert "task_id" in data, "No task_id"
    assert data["status"] in ("pending", "running"), f"Unexpected status: {data['status']}"
    task_ids["task_a"] = data["task_id"]

@pytest.mark.e2e
def test_task_processing():
    task_id = task_ids["task_a"]
    headers = {"Authorization": f"Bearer {tokens['user_a']}"}
    for i in range(20):
        time.sleep(3)
        resp = requests.get(f"{BASE}/tasks/{task_id}", headers=headers)
        data = resp.json()
        status = data["status"]
        progress = data["progress"]
        if status == "success":
            assert progress == 100, f"Success but progress={progress}"
            return
        if status == "failed":
            raise AssertionError(f"Task failed: {data.get('error')}")
    raise AssertionError(f"Timed out: {data['status']}")

# ============================================================
# 4. Knowledge Workspace
# ============================================================
@pytest.mark.e2e
def test_knowledge():
    headers = {"Authorization": f"Bearer {tokens['user_a']}"}
    resp = requests.get(f"{BASE}/knowledge", headers=headers)
    assert resp.status_code == 200, f"Knowledge: {resp.status_code} {resp.text}"
    data = resp.json()
    assert "documents" in data, "No documents field"
    assert data["document_count"] >= 1, f"Expected at least 1 doc, got {data['document_count']}"

# ============================================================
# 5. Chat Copilot
# ============================================================
@pytest.mark.e2e
def test_chat():
    headers = {"Authorization": f"Bearer {tokens['user_a']}"}
    resp = requests.post(f"{BASE}/chat", json={
        "question": "Summarize this financial report"
    }, headers=headers)
    assert resp.status_code == 200, f"Chat: {resp.status_code} {resp.text[:300]}"
    data = resp.json()
    assert "report" in data, f"No 'report' field: {list(data.keys())}"
    assert "citations" in data, "No 'citations' field"
    assert "execution_time" in data, "No 'execution_time' field"

# ============================================================
# 6. Multi-Tenant Isolation
# ============================================================
@pytest.mark.e2e
def test_tenant_isolation():
    # Register User B
    resp = requests.post(f"{BASE}/auth/register", json={
        "email": EMAIL_B,
        "password": "Test@123456",
        "name": "Test User B"
    })
    assert resp.status_code == 201, f"Register B: {resp.status_code} {resp.text}"
    token_b = resp.json()["token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Upload Apple PDF for User B
    pdf_content = _valid_pdf("Apple financial report. Revenue: 100 billion USD.")
    files = {"file": ("apple_report.pdf", io.BytesIO(pdf_content), "application/pdf")}
    resp = requests.post(f"{BASE}/upload", files=files, headers=headers_b)
    assert resp.status_code == 200, f"Upload B: {resp.status_code} {resp.text}"
    task_id_b = resp.json()["task_id"]

    # Wait for task
    for i in range(20):
        time.sleep(3)
        resp = requests.get(f"{BASE}/tasks/{task_id_b}", headers=headers_b)
        if resp.json()["status"] == "success":
            break
        if resp.json()["status"] == "failed":
            raise AssertionError(f"Task B failed: {resp.json().get('error')}")

    # User A's documents (should only see Tesla, NOT Apple)
    headers_a = {"Authorization": f"Bearer {tokens['user_a']}"}
    resp = requests.get(f"{BASE}/knowledge", headers=headers_a)
    assert resp.status_code == 200, f"Docs A: {resp.status_code}"
    docs_a = resp.json()
    doc_names_a = [d for d in docs_a["documents"]]
    assert "apple" not in [d.lower() for d in doc_names_a], f"User A leaked Apple: {doc_names_a}"

    # User B's documents (should only see Apple, NOT Tesla)
    resp = requests.get(f"{BASE}/knowledge", headers=headers_b)
    assert resp.status_code == 200, f"Docs B: {resp.status_code}"
    docs_b = resp.json()
    doc_names_b = [d for d in docs_b["documents"]]
    assert "tesla" not in [d.lower() for d in doc_names_b], f"User B leaked Tesla: {doc_names_b}"

# ============================================================
# 7. Docker Runtime
# ============================================================

SERVICE_ALIASES: dict[str, tuple[str, ...]] = {
    "backend": ("backend", "api"),
    "frontend": ("frontend", "nginx"),
    "worker": ("agent-worker", "worker"),
    "redis": ("redis",),
    "chromadb": ("chromadb",),
}


def _compose_project() -> str:
    """Return the Compose project name used to discover running containers.

    Resolution order:
    1. ``E2E_COMPOSE_PROJECT`` environment variable
    2. ``COMPOSE_PROJECT_NAME`` environment variable
    3. ``financial-rag-prod`` default (historical production project name)
    """
    import os as _os
    return (
        _os.environ.get("E2E_COMPOSE_PROJECT")
        or _os.environ.get("COMPOSE_PROJECT_NAME")
        or "financial-rag-prod"
    )


def _resolve_container(service: str) -> str:
    """Discover the first running container for *service* in the current
    Compose project by inspecting Docker labels.

    Returns the container ID (not the friendly name) so callers can pass it
    directly to ``docker logs`` or ``docker inspect``.
    """
    project = _compose_project()
    result = subprocess.run(
        [
            "docker", "ps",
            "--filter", f"label=com.docker.compose.project={project}",
            "--filter", f"label=com.docker.compose.service={service}",
            "--filter", "status=running",
            "--format", "{{.ID}}",
            "--no-trunc",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    container_id = result.stdout.strip().split("\n")[0].strip()
    if not container_id:
        raise RuntimeError(
            f"No running container found for service '{service}' "
            f"in Compose project '{project}'. "
            "Is the stack running?"
        )
    return container_id


def _running_service_names() -> set[str]:
    """Return the set of Compose service names that are currently running."""
    project = _compose_project()
    result = subprocess.run(
        [
            "docker", "ps",
            "--filter", f"label=com.docker.compose.project={project}",
            "--filter", "status=running",
            "--format", "{{.Label \"com.docker.compose.service\"}}",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return {name.strip() for name in result.stdout.strip().split("\n") if name.strip()}


def _resolve_logical_service(logical: str, running: set[str]) -> str:
    """Resolve *logical* service name to the actual running Compose service.

    Uses ``SERVICE_ALIASES`` to map logical names to the active alias present
    in *running*.  Raises ``AssertionError`` with a clear diagnostic when no
    alias matches.
    """
    aliases = SERVICE_ALIASES.get(logical, (logical,))
    for alias in aliases:
        if alias in running:
            return alias
    raise AssertionError(
        f"Logical service '{logical}' not found among running services. "
        f"Accepted aliases: {aliases}. "
        f"Running services: {sorted(running)}"
    )


@pytest.mark.e2e
def test_docker_runtime():
    services = _running_service_names()
    project = _compose_project()
    missing = []
    for logical in ("backend", "frontend", "redis", "chromadb"):
        try:
            _resolve_logical_service(logical, services)
        except AssertionError:
            missing.append(logical)
    assert len(missing) == 0, (
        f"Missing logical services: {missing}. "
        f"Running Compose services: {sorted(services)}. "
        f"Project: {project}"
    )


@pytest.mark.e2e
def test_worker_heartbeat():
    services = _running_service_names()
    worker_svc = _resolve_logical_service("worker", services)
    container_id = _resolve_container(worker_svc)

    result = subprocess.run(
        ["docker", "logs", container_id],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    combined = (result.stdout + result.stderr).lower()
    assert (
        "worker runner started" in combined
        or "waiting for tasks" in combined
        or "taskworker started" in combined
    ), "No heartbeat in logs"


if __name__ == "__main__":
    _e2e_test("2.1 Register User A", test_register)
    _e2e_test("2.2 /auth/me with tenant", test_me)
    _e2e_test("2.3 Login returns access_token", test_login)
    _e2e_test("3.1 Upload PDF -> task created", test_upload_pdf)
    _e2e_test("3.2 Task pending->running->success", test_task_processing)
    _e2e_test("4.1 Knowledge /knowledge endpoint", test_knowledge)
    _e2e_test("5.1 Chat copilot with question", test_chat)
    _e2e_test("6.1 Multi-tenant isolation", test_tenant_isolation)
    _e2e_test("7.1 Docker containers healthy", test_docker_runtime)
    _e2e_test("7.2 Worker heartbeat running", test_worker_heartbeat)
    report()
