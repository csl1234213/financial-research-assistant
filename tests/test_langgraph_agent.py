import sys
import types
from unittest.mock import MagicMock

from langgraph.checkpoint.memory import InMemorySaver

from core.rag_result import RAGResult
from observability.tracer import start_trace
from services.agent_runtime.checkpointing import scoped_checkpoint_thread_id
from services.agent_runtime.graph import _actual_tools_used, build_agent_graph, run_agent


def _fake_run_rag(question, **_scope):
    plan = MagicMock()
    plan.intent = "single_company"
    plan.tasks = []
    return RAGResult(
        report=f"Report for: {question}",
        citations=[
            {
                "source": "Tesla_Q2_2025.pdf",
                "chunk_id": "tesla_0",
                "similarity": 0.9,
            }
        ],
        context="retrieved context",
        research_mode="default",
        intent={"intent": "SINGLE_COMPANY", "companies": ["Tesla"]},
        evidence=[],
        plan=plan,
        routing={"provider": "deepseek", "model": "deepseek-v4-flash"},
        planning={"task_type": "document_qa"},
        execution={"strategy": "rag", "use_retrieval": True, "use_tools": False},
        workflow={"type": "rag", "status": "DONE"},
    )


def test_source_controlled_langgraph_runs_the_rag_execution_node(monkeypatch):
    received_scope = {}

    def fake_run_rag(question, **scope):
        received_scope.update(scope)
        return _fake_run_rag(question, **scope)

    fake_core_engine = types.ModuleType("core.core_engine")
    fake_core_engine.run_rag = fake_run_rag
    monkeypatch.setitem(sys.modules, "core.core_engine", fake_core_engine)
    build_agent_graph.cache_clear()

    result = run_agent(
        "Analyze Tesla revenue growth",
        company="Tesla",
        thread_id="thread-1",
        tenant_id=7,
        history=[{"role": "user", "content": "Focus on revenue."}],
    )

    assert result["answer"] == "Report for: Analyze Tesla revenue growth"
    assert result["thread_id"] == "thread-1"
    assert result["tools_used"] == ["retrieval"]
    assert result["companies"] == ["Tesla"]
    assert result["sources"][0]["source"] == "Tesla_Q2_2025.pdf"
    assert result["citations"][0]["source"] == "Tesla_Q2_2025.pdf"
    assert result["plan"]["intent"] == "single_company"
    assert result["intent"]["intent"] == "SINGLE_COMPANY"
    assert result["workflow"]["type"] == "rag"
    assert result["execution"]["strategy"] == "rag"
    assert received_scope["company"] == "Tesla"


def test_langgraph_reports_only_observed_tool_execution():
    planned_only = _actual_tools_used(
        plan_steps=[
            {
                "step_type": "retrieve",
                "status": "skipped",
                "tool_name": None,
            },
            {
                "step_type": "tool_call",
                "status": "failed",
                "tool_name": "python",
            },
        ],
        citations=[],
        execution={"use_retrieval": True, "use_tools": True},
    )
    completed_retrieval = _actual_tools_used(
        plan_steps=[
            {
                "step_type": "tool_call",
                "status": "completed",
                "tool_name": "retrieval",
            },
        ],
        citations=[],
        execution={"use_retrieval": False, "use_tools": True},
    )

    assert planned_only == []
    assert completed_retrieval == ["retrieval"]


def test_langgraph_traces_actual_node_execution(monkeypatch):
    fake_core_engine = types.ModuleType("core.core_engine")
    fake_core_engine.run_rag = _fake_run_rag
    monkeypatch.setitem(sys.modules, "core.core_engine", fake_core_engine)
    build_agent_graph.cache_clear()
    trace = start_trace(thread_id="trace-thread", tenant_id=7)

    run_agent(
        "Analyze Tesla revenue growth",
        thread_id="trace-thread",
        tenant_id=7,
        trace=trace,
    )

    assert [span.node_name for span in trace.spans] == [
        "intent_analysis",
        "rag_execution",
        "response_finalize",
    ]
    assert all(span.status == "success" for span in trace.spans)
    assert all(span.duration_ms is not None for span in trace.spans)


def test_langgraph_checkpointer_persists_serializable_graph_state(monkeypatch):
    fake_core_engine = types.ModuleType("core.core_engine")
    fake_core_engine.run_rag = _fake_run_rag
    monkeypatch.setitem(sys.modules, "core.core_engine", fake_core_engine)
    checkpointer = InMemorySaver()
    checkpoint_thread_id = scoped_checkpoint_thread_id(7, 42, "default")
    config = {"configurable": {"thread_id": checkpoint_thread_id}}

    first = run_agent(
        "Analyze Tesla revenue",
        thread_id="default",
        tenant_id=7,
        user_id=42,
        checkpointer=checkpointer,
        checkpoint_thread_id=checkpoint_thread_id,
    )
    second = run_agent(
        "Analyze Tesla margin",
        thread_id="default",
        tenant_id=7,
        user_id=42,
        checkpointer=checkpointer,
        checkpoint_thread_id=checkpoint_thread_id,
    )

    saved = checkpointer.get_tuple(config)
    assert saved is not None
    assert saved.checkpoint["channel_values"]["answer"] == second["answer"]
    assert first["answer"] != second["answer"]
    assert len(list(checkpointer.list(config))) >= 2


def test_checkpoint_thread_ids_are_isolated_by_user():
    first = scoped_checkpoint_thread_id(7, 41, "default")
    second = scoped_checkpoint_thread_id(7, 42, "default")

    assert first != second
    assert "default" not in first
