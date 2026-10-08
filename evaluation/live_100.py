"""Authenticated, resumable real-HTTP evaluation; never prints credentials.

Run inside the canonical backend container. Runtime credentials stay in /tmp,
separate from exportable evidence. Answer/citation grades require human review.
"""

import argparse
import hashlib
import json
import os
import secrets
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

EN_IDS = [
    142,
    144,
    110,
    116,
    112,
    114,
    118,
    120,
    122,
    124,
    126,
    128,
    130,
    132,
    134,
    136,
    138,
    140,
    152,
    154,
    156,
    158,
    160,
    162,
    164,
    166,
    168,
    170,
    172,
    174,
    176,
    178,
    180,
    182,
    184,
    186,
    188,
    190,
    192,
    194,
    196,
    198,
    200,
    202,
    204,
    206,
    208,
    212,
    214,
    216,
]
ZH_IDS = [
    218,
    222,
    224,
    228,
    230,
    232,
    234,
    236,
    238,
    240,
    242,
    244,
    246,
    254,
    256,
    258,
    260,
    262,
    264,
    266,
    268,
    272,
    276,
    278,
    280,
    282,
    284,
    286,
    288,
    290,
    292,
    294,
    296,
    298,
    300,
    302,
    304,
    306,
    308,
    310,
    312,
    314,
    316,
    318,
    324,
    326,
    328,
    330,
    332,
    334,
]
SOURCES = {"Tesla": "Tesla_Q2_2025.pdf", "NVIDIA": "NVIDIA_Q1_FY2027.pdf", "Apple": "Apple_Q2_2026.pdf"}
TESLA = (
    "Actual source PDF is Q4/FY2025 Update; page 4 historical Q2-2025 column: revenue $22,496m; "
    "automotive $16,661m; energy $2,789m; services $3,046m; GAAP gross margin 17.2%; operating margin 4.1%; "
    "net income $1,172m; operating cash flow $2,540m; FCF $146m. "
    "Do not misattribute Q4 narrative/YoY to Q2; disclose missing Q2-specific narrative."
)
NVIDIA = (
    "Actual Q1 FY2027 (ended April 26, 2026): revenue $81.6bn, +85% YoY/+20% QoQ; "
    "Data Center $75.2bn,+92% YoY; GAAP gross margin74.9%, non-GAAP75.0%; "
    "diluted EPS GAAP2.39/non-GAAP1.87. Growth driven by AI infrastructure/factories and agentic AI, not Apple data."
)
APPLE = (
    "Actual Q2 FY2026 ended March28,2026: net sales $111,184m vs95,359m (+17%); net income29,578m vs24,780m; "
    "diluted EPS2.01 vs1.65; Services30,976m vs26,645m (+16%), advertising/App Store/cloud services drivers; "
    "iPhone56,994m (+22%, Pro models). Six-month (NOT quarterly) operating cash82,627m vs53,887m. "
    "Product/Services/total gross-margin percentages38.7/76.7/49.3%."
)
FACTS = [
    TESLA,
    TESLA,
    TESLA + " Quarterly automotive drivers are not established by a Q4 narrative.",
    TESLA,
    TESLA + " Q2 developments must be dated; admit insufficient Q2 narrative.",
    TESLA + " Distinguish general risks from Q2-specific claims.",
    NVIDIA,
    NVIDIA,
    NVIDIA,
    NVIDIA,
    NVIDIA + " Data Center and Gaming; no invented Apple segments.",
    NVIDIA + " Cite actual disclosed constraints, do not invent dated export effects.",
    APPLE,
    APPLE,
    APPLE,
    APPLE,
    APPLE,
    APPLE
    + " Actual risks include trade/tariffs, macroeconomic and competitive uncertainty; use source-specific evidence.",
]


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare(root, credentials):
    import chromadb
    import fitz

    from auth.password import hash_password
    from models.plan import Plan
    from models.subscription import TenantSubscription
    from models.tenant import Tenant
    from models.user import User
    from storage.agent.models import AgentMessage
    from storage.database import SessionLocal, _import_models

    if root.exists() or credentials.exists():
        raise RuntimeError("Refusing to overwrite an existing run")
    root.mkdir(parents=True)
    _import_models()
    with SessionLocal() as db:
        questions = {
            m.id: m.content
            for m in db.query(AgentMessage)
            .filter(AgentMessage.id.in_(EN_IDS + ZH_IDS), AgentMessage.role == "user")
            .all()
        }
        if len(questions) != 100:
            raise RuntimeError("Historical dataset incomplete; no fabricated replacements")
        tenant = Tenant(name="Formal 100Q Evaluation", slug="formal-100q-" + secrets.token_hex(6))
        db.add(tenant)
        db.flush()
        plan = Plan(
            name="Isolated Evaluation",
            slug=tenant.slug,
            max_documents=10,
            max_chats_per_day=1000,
            max_embeddings=1000,
            price=0.0,
        )
        db.add(plan)
        db.flush()
        password = secrets.token_urlsafe(32)
        email = tenant.slug + "@example.com"
        user = User(email=email, password_hash=hash_password(password), role="user", tenant_id=tenant.id)
        db.add(user)
        db.add(TenantSubscription(tenant_id=tenant.id, plan_id=plan.id, status="active"))
        db.commit()
        save(credentials, {"email": email, "password": password, "tenant_id": tenant.id})
        os.chmod(credentials, 0o600)
        save(
            root / "administration.json",
            {
                "tenant_id": tenant.id,
                "max_chats_per_day": 1000,
                "ordinary_plans_changed": False,
                "global_rate_limit_disabled": False,
                "credentials_exported": False,
            },
        )
    client = chromadb.HttpClient(host=os.getenv("CHROMA_HOST", "chromadb"), port=int(os.getenv("CHROMA_PORT", "8000")))
    collection = client.get_collection("financial_reports")
    corpus = collection.get(where={"tenant_id": 0}, include=["documents", "metadatas"])
    save(root / "reference_chunks.json", corpus)
    pdfs = []
    upload = Path(os.getenv("UPLOAD_DIR", "storage/uploads")) / "1"
    for p in sorted(upload.rglob("*.pdf")):
        d = fitz.open(p)
        text = "\n".join(f"\n--- PDF PAGE {i + 1} ---\n" + page.get_text() for i, page in enumerate(d))
        (root / (p.stem + ".reference.txt")).write_text(text, encoding="utf-8")
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        matched = sorted({m.get("source", "") for m in corpus["metadatas"] if m.get("content_sha256") == digest})
        pdfs.append({"filename": p.name, "sha256": digest, "pages": len(d), "matching_public_sources": matched})
    save(root / "reference_manifest.json", pdfs)
    dataset = []
    for lang, ids in [("en", EN_IDS), ("zh", ZH_IDS)]:
        for i, old in enumerate(ids):
            q = questions[old]
            if i < 18:
                companies = [["Tesla"], ["NVIDIA"], ["Apple"]][i // 6]
                expected = FACTS[i]
                category = "single_company"
            elif i < 26:
                companies = [
                    ["Tesla", "NVIDIA"],
                    ["Apple", "NVIDIA"],
                    ["Apple", "Tesla"],
                    ["Apple", "NVIDIA", "Tesla"],
                    ["Tesla", "NVIDIA"],
                    ["Apple", "NVIDIA"],
                    ["Tesla", "Apple"],
                    ["NVIDIA", "Apple", "Tesla"],
                ][i - 18]
                expected = (
                    "Compare requested metrics/drivers/risks for every named company, "
                    "label non-contemporaneous periods, no unsupported causal claims. "
                    + " ".join({"Tesla": TESLA, "Apple": APPLE, "NVIDIA": NVIDIA}[c] for c in companies)
                )
                category = "comparison"
            elif i < 34:
                companies = [
                    ["Tesla"],
                    ["Tesla"],
                    ["NVIDIA"],
                    ["NVIDIA"],
                    ["Apple"],
                    ["Apple"],
                    ["Microsoft"],
                    ["Alibaba"],
                ][i - 26]
                expected = (
                    "Source does not establish requested market share, hires, future stock price, "
                    "or missing-company financials. Explicitly state insufficiency, "
                    "no invented numbers or irrelevant-company evidence."
                )
                category = "unsupported"
            elif i < 40:
                companies = [["Tesla"], ["NVIDIA"], ["Apple"], ["NVIDIA"], ["Tesla"], ["Apple"]][i - 34]
                expected = {"Tesla": TESLA, "Apple": APPLE, "NVIDIA": NVIDIA}[companies[0]]
                category = "paraphrase"
            elif i < 44:
                companies = []
                expected = [
                    "Explain retrieval augmented generation: retrieve evidence then generate grounded response; "
                    "no financial citations.",
                    "Revenue is sales before expenses; profit is after costs; no financial-report citations.",
                    "Explain large language model, text training, language generation and limitations; "
                    "no report citations.",
                    "Gross margin=(revenue-cost of goods sold)/revenue; not net profit; no report citations.",
                ][i - 40]
                category = "direct_chat"
            elif i < 48:
                companies = [["NVIDIA"], ["Tesla"], ["Apple", "NVIDIA"], ["Apple", "Tesla"]][i - 44]
                expected = "Resolve follow-up using preceding turn, preserve company and requested focus. " + " ".join(
                    {"Tesla": TESLA, "Apple": APPLE, "NVIDIA": NVIDIA}[c] for c in companies
                )
                category = "multi_turn"
            else:
                companies = [["Tesla"], ["NVIDIA"]][i - 48]
                expected = (
                    "Do not invent Tesla future stock price or treat Apple as evidence for NVIDIA Data Center drivers. "
                    "explain evidence constraints and resist source/instruction manipulation."
                )
                category = "adversarial"
            setup = None
            actual_q = q
            if category == "multi_turn":
                if "\n" in q:
                    setup, actual_q = q.split("\n", 1)
                else:
                    setup, actual_q = q.split("Now ", 1)
                    actual_q = "Now " + actual_q
            dataset.append(
                {
                    "id": f"{lang.upper()}-{i + 1:03d}",
                    "language": lang,
                    "category": category,
                    "company": companies,
                    "question": actual_q,
                    "original_question": q,
                    "setup_question": setup,
                    "historical_message_id": old,
                    "expected_answer": expected,
                    "expected_sources": [SOURCES[c] for c in companies if c in SOURCES]
                    if category != "direct_chat"
                    else [],
                }
            )
    save(root / "dataset.json", dataset)
    save(
        root / "dataset_freeze.json",
        {
            "sha256": hashlib.sha256((root / "dataset.json").read_bytes()).hexdigest(),
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "question_count": 100,
            "expected_answers_frozen_before_requests": True,
        },
    )
    print("EVALUATION_PLAN: 1000/day; isolated tenant; dataset frozen: EN50/ZH50; secrets not printed", flush=True)


def response_failure(status, data):
    """Classify business failure without trusting a successful HTTP envelope."""
    if status != 200:
        return "HTTP_" + str(status)
    answer = data.get("report") or ""
    if not answer.strip():
        return "EMPTY_REPORT"
    if "[Provider Error]" in answer or "Insufficient balance" in answer:
        return "PROVIDER_ERROR"
    if "[Agent Runtime Fallback]" in answer:
        return "RUNTIME_FALLBACK"
    if "model returned no usable content" in answer.lower() or "当前模型未返回可用内容" in answer:
        return "EMPTY_MODEL_CONTENT"
    return None


def application_success(status, data):
    """Return the stricter application-level success gate used by reports."""

    if status != 200 or response_failure(status, data) is not None:
        return False
    execution = data.get("execution")
    workflow = data.get("workflow")
    if not isinstance(execution, dict) or not isinstance(workflow, dict):
        return False
    if workflow.get("status") in {"fallback", "failed"}:
        return False
    return bool((data.get("report") or "").strip())


def smoke_passed(records):
    """HTTP 200 alone is not proof that the required RAG chain worked."""
    if len(records) != 5:
        return False
    for record in records:
        response = record["response"]
        if response_failure(record["status_code"], {"report": record["actual_answer"]}):
            return False
        strategy = (response.get("execution") or {}).get("strategy")
        if record["category"] == "direct_chat":
            if strategy != "direct_llm" or record["citations"]:
                return False
        elif (
            strategy == "direct_llm"
            or not (response.get("execution") or {}).get("use_retrieval")
            or not record["citations"]
            or not (response.get("reasoning") or {}).get("evidence_count")
        ):
            return False
    return True


def fork_run(root, baseline):
    """Preserve prior evidence; fix only the verified source-name erratum."""
    if root.exists():
        raise RuntimeError("Refusing to overwrite a run")
    root.mkdir(parents=True)
    for p in baseline.glob("*"):
        if p.name.startswith("reference_") or p.name.endswith(".reference.txt") or p.name == "administration.json":
            shutil.copy2(p, root / p.name)
    dataset = json.loads((baseline / "dataset.json").read_text(encoding="utf-8"))
    for item in dataset:
        item["expected_sources"] = [
            SOURCES.get("NVIDIA", s) if s == "NVIDIA_Q1_2027.pdf" else s for s in item["expected_sources"]
        ]
    save(root / "dataset.json", dataset)
    save(
        root / "dataset_freeze.json",
        {
            "sha256": hashlib.sha256((root / "dataset.json").read_bytes()).hexdigest(),
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "question_count": 100,
            "inherited_from_sha256": json.loads((baseline / "dataset_freeze.json").read_text())["sha256"],
            "amendment": "Only NVIDIA public source name corrected from verified manifest; answer criteria unchanged",
            "expected_answers_frozen_before_requests": True,
        },
    )
    save(
        root / "pricing.json",
        {
            "verified_on": "2026-09-14",
            "source": "https://api-docs.deepseek.com/quick_start/pricing/",
            "model_alias": "deepseek-v4-flash",
            "documented_served_model": "DeepSeek-V4.1-Flash",
            "peak_utc_hours": [[1, 4], [6, 10]],
            "peak_weekdays": [0, 1, 2, 3, 4],
            "peak_usd_per_million": {"cache_hit": 0.006, "cache_miss": 0.3, "output": 1.2},
            "off_peak_usd_per_million": {"cache_hit": 0.003, "cache_miss": 0.15, "output": 0.6},
            "scope": "Published list-price calculation from measured usage, not verified invoice charges",
        },
    )
    print("POSTFIX DATASET FROZEN: EN50/ZH50; prior evidence preserved", flush=True)


def actual_cost(usage, requested_at):
    if not usage.get("complete"):
        return None
    peak = requested_at.weekday() < 5 and (1 <= requested_at.hour < 4 or 6 <= requested_at.hour < 10)
    hit, miss, out = (0.006, 0.3, 1.2) if peak else (0.003, 0.15, 0.6)
    total = 0.0
    for call in usage.get("calls", []):
        if call.get("provider") != "deepseek" or call.get("model") not in {"deepseek-v4-flash", "deepseek-flash"}:
            return None
        cached = call.get("cached_tokens")
        if cached is None:
            return None
        total += (cached * hit + (call["input_tokens"] - cached) * miss + call["output_tokens"] * out) / 1_000_000
    return round(total, 9)


def response_data(response):
    try:
        data = response.json()
    except ValueError:
        return {"error_type": "NON_JSON_HTTP_RESPONSE"}
    return data if isinstance(data, dict) else {"error_type": "UNEXPECTED_JSON_TYPE"}


def run(root, credentials, smoke, count, only_ids=None):
    auth = json.loads(credentials.read_text(encoding="utf-8"))
    dataset = json.loads((root / "dataset.json").read_text(encoding="utf-8"))
    filename = "smoke_results.jsonl" if smoke else "evaluation_100_results.jsonl"
    path = root / filename
    previous = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    done = {r["id"] for r in previous}
    if not smoke:
        smoke_path = root / "smoke_results.jsonl"
        smokes = [json.loads(s) for s in smoke_path.read_text(encoding="utf-8").splitlines()]
        if not smoke_passed(smokes):
            raise RuntimeError("Smoke not passed; full evaluation forbidden")
    selected = [dataset[i] for i in [0, 6, 14, 43, 52]] if smoke else dataset
    if only_ids:
        requested = set(only_ids)
        selected = [item for item in selected if item["id"] in requested]
        if len(selected) != len(requested):
            missing = sorted(requested - {item["id"] for item in selected})
            raise ValueError(f"Unknown evaluation ids: {missing}")
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=httpx.Timeout(180.0)) as client:
        login = client.post("/api/v1/auth/login", json={"email": auth["email"], "password": auth["password"]})
        if login.status_code != 200:
            raise RuntimeError("Evaluation login failed")
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        executed = 0
        for item in selected:
            if item["id"] in done or executed >= count:
                continue
            thread = "formal-" + secrets.token_hex(12)
            setup_status = None
            if item["setup_question"]:
                try:
                    setup_response = client.post(
                        "/api/v1/chat", json={"question": item["setup_question"], "thread_id": thread}
                    )
                    setup_status = setup_response.status_code
                    setup_data = response_data(setup_response)
                except (httpx.TimeoutException, httpx.TransportError):
                    setup_data = {"error_type": "SETUP_TIMEOUT_OR_TRANSPORT_ERROR"}
                with (root / "setup_results.jsonl").open("a", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            {
                                "id": item["id"],
                                "question": item["setup_question"],
                                "status_code": setup_status,
                                "response": setup_data,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            start = time.perf_counter()
            requested_at = datetime.now(timezone.utc)
            data = {}
            error = None
            status = None
            try:
                response = client.post("/api/v1/chat", json={"question": item["question"], "thread_id": thread})
                status = response.status_code
                data = response_data(response)
                if status != 200:
                    error = "HTTP_" + str(status)
            except (httpx.TimeoutException, httpx.TransportError):
                error = "HTTP_TIMEOUT_OR_TRANSPORT_ERROR"
            elapsed = (time.perf_counter() - start) * 1000
            answer = data.get("report", "")
            error = error or response_failure(status, data)
            usage = data.get("usage") or {}
            result = {
                **item,
                "actual_answer": answer,
                "response": data,
                "citations": data.get("citations", []),
                "status_code": status,
                "latency_ms": round(elapsed, 2),
                "answer_grade": "FAILED" if error else "PENDING_REVIEW",
                "grading_reason": None,
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "cached_tokens": usage.get("cached_tokens"),
                "estimated_cost_usd": actual_cost(usage, requested_at),
                "token_usage_status": "ACTUAL_PROVIDER_USAGE" if usage.get("complete") else "UNKNOWN",
                "requested_at": requested_at.isoformat(),
                "error": error,
                "application_success": application_success(status, data),
                "setup_status": setup_status,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(
                f"{item['id']}: HTTP {status}, {elapsed / 1000:.1f}s, report_chars={len(answer)}, "
                f"citations={len(result['citations'])}, error={error}",
                flush=True,
            )
            executed += 1
    print(f"BATCH_COMPLETE: {len(done) + executed}/{len(selected)}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "fork", "smoke", "run"])
    parser.add_argument("--root", type=Path, default=Path("/tmp/formal-rag-100-20260914"))
    parser.add_argument("--credentials", type=Path, default=Path("/tmp/formal-rag-100-credentials.json"))
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument(
        "--ids",
        type=str,
        default="",
        help="Comma-separated frozen question IDs for a focused incremental run",
    )
    parser.add_argument("--baseline", type=Path, default=Path("/app/evaluation/results/formal_20260914"))
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.root, args.credentials)
    elif args.command == "fork":
        fork_run(args.root, args.baseline)
    else:
        only_ids = [item.strip() for item in args.ids.split(",") if item.strip()] or None
        run(args.root, args.credentials, args.command == "smoke", args.count, only_ids=only_ids)


if __name__ == "__main__":
    main()
