"""Source-controlled LangGraph orchestration for the Financial Agent.

The graph intentionally reuses the established RAG runtime as its execution
node.  LangGraph owns the stateful orchestration contract; the existing
runtime remains the domain implementation for planning, retrieval, and model
routing.  This avoids maintaining two divergent Agent implementations.
"""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from functools import lru_cache
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime


class AgentGraphState(TypedDict, total=False):
    question: str
    company: str | None
    thread_id: str
    tenant_id: int
    user_id: int | None
    history: list[dict[str, Any]]
    initial_intent: dict[str, Any]
    report: str
    citations: list[dict[str, Any]]
    context: str
    research_mode: str
    intent: dict[str, Any]
    plan_summary: dict[str, Any]
    routing: dict[str, Any] | None
    planning: dict[str, Any] | None
    execution: dict[str, Any] | None
    workflow: dict[str, Any] | None
    evidence_count: int
    answer: str
    sources: list[dict[str, Any]]
    tools_used: list[str]
    companies: list[str]
    research_plan: list[dict[str, Any]]
    quality_score: float
    critique: dict[str, Any]
    revision_count: int


class AgentGraphContext(TypedDict, total=False):
    trace: Any
    llm_settings: Any
    deadline: float | None
    answer_language: str | None


def _trace_node(
    runtime: Runtime[AgentGraphContext],
    node_name: str,
    metadata: dict[str, Any],
) -> AbstractContextManager[Any]:
    """Create a real graph-node span when request tracing is enabled."""

    trace = (runtime.context or {}).get("trace")
    if trace is None:
        return nullcontext()

    from observability.tracer import node_span

    return node_span(trace, node_name, metadata=metadata)


def _plan_node(
    state: AgentGraphState,
    runtime: Runtime[AgentGraphContext],
) -> dict[str, Any]:
    """Expose an explicit planning node before the runtime executes."""
    from core.intent_analyzer import IntentAnalyzer

    with _trace_node(
        runtime,
        "intent_analysis",
        {"thread_id": state.get("thread_id", "default")},
    ):
        initial_intent = IntentAnalyzer().analyze(state["question"])
    return {"initial_intent": initial_intent}


def _serialize_plan(plan: Any, intent: dict[str, Any]) -> dict[str, Any]:
    tasks = [
        {
            "step_id": step.step_id,
            "step_type": step.step_type.value,
            "description": step.description,
            "company": step.company,
            "status": step.status.value,
            "tool_name": getattr(step, "tool_name", None),
        }
        for step in getattr(plan, "tasks", [])
    ]
    return {
        "intent": getattr(plan, "intent", intent.get("intent", "")),
        "task_count": len(tasks),
        "tasks": tasks,
    }


def _execute_node(
    state: AgentGraphState,
    runtime: Runtime[AgentGraphContext],
) -> dict[str, Any]:
    """Run the established tenant-aware RAG runtime as one graph node."""
    from core.core_engine import run_rag

    with _trace_node(
        runtime,
        "rag_execution",
        {
            "thread_id": state.get("thread_id", "default"),
            "tenant_id": state.get("tenant_id", 0),
            "company": state.get("company"),
        },
    ):
        result = run_rag(
            state["question"],
            company=state.get("company"),
            tenant_id=state.get("tenant_id", 0),
            thread_id=state.get("thread_id"),
            conversation_history=state.get("history", []),
            llm_settings=(runtime.context or {}).get("llm_settings"),
            deadline=(runtime.context or {}).get("deadline"),
            answer_language=(runtime.context or {}).get("answer_language"),
        )
    return {
        "report": result.report,
        "citations": result.citations,
        "context": result.context,
        "research_mode": result.research_mode,
        "intent": result.intent,
        "evidence_count": len(result.evidence),
        "plan_summary": _serialize_plan(result.plan, result.intent),
        "routing": result.routing,
        "planning": result.planning,
        "execution": result.execution,
        "workflow": result.workflow,
    }


def _finalize_node(
    state: AgentGraphState,
    runtime: Runtime[AgentGraphContext],
) -> dict[str, Any]:
    with _trace_node(
        runtime,
        "response_finalize",
        {"thread_id": state.get("thread_id", "default")},
    ):
        execution = state.get("execution") or {}
        citations = state.get("citations") or []
        intent = state.get("intent") or state.get("initial_intent") or {}
        plan_summary = state.get("plan_summary") or {
            "intent": intent.get("intent", ""),
            "task_count": 0,
            "tasks": [],
        }

        plan_steps = plan_summary["tasks"]
        tools_used = _actual_tools_used(
            plan_steps=plan_steps,
            citations=citations,
            execution=execution,
        )

        sources = [
            {
                "source": citation.get("source", ""),
                "chunk_id": citation.get("chunk_id", ""),
                "similarity": citation.get("similarity"),
                "preview": citation.get("preview", ""),
            }
            for citation in citations
        ]
        answer = state.get("report", "")
        quality_score = (
            1.0
            if answer and (not execution.get("use_retrieval") or citations)
            else 0.0
        )

        return {
            "answer": answer,
            "sources": sources,
            "tools_used": tools_used,
            "companies": intent.get("companies") or [],
            "research_plan": plan_steps,
            "plan_summary": plan_summary,
            "quality_score": quality_score,
            "critique": {
                "status": "not_evaluated",
                "reason": "Runtime completion score only; offline golden evaluation is separate.",
            },
            "revision_count": 0,
        }


def _actual_tools_used(
    *,
    plan_steps: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    execution: dict[str, Any],
) -> list[str]:
    """Report observed tool execution, never strategy intent alone."""
    observed: list[str] = []

    # A completed retrieval step records a real handler invocation. Citations
    # are also sufficient evidence for adapters that do not expose plan steps
    # (for example, compatibility callers and test doubles).
    if any(
        step.get("step_type") == "retrieve" and step.get("status") == "completed"
        for step in plan_steps
    ) or (citations and execution.get("use_retrieval")):
        observed.append("retrieval")

    for step in plan_steps:
        if step.get("step_type") != "tool_call" or step.get("status") != "completed":
            continue
        tool_name = step.get("tool_name")
        if isinstance(tool_name, str) and tool_name and tool_name not in observed:
            observed.append(tool_name)

    return observed


def _build_graph() -> StateGraph:
    graph = StateGraph(AgentGraphState, context_schema=AgentGraphContext)
    graph.add_node("plan", _plan_node)
    graph.add_node("execute", _execute_node)
    graph.add_node("finalize", _finalize_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "finalize")
    graph.add_edge("finalize", END)
    return graph


@lru_cache(maxsize=1)
def build_agent_graph():
    """Compile the stateless graph once for tests and anonymous requests."""

    return _build_graph().compile()


def build_persistent_agent_graph(checkpointer: BaseCheckpointSaver):
    """Compile the graph with a real LangGraph persistence backend."""

    return _build_graph().compile(checkpointer=checkpointer)


def run_agent(
    question: str,
    *,
    company: str | None = None,
    thread_id: str = "default",
    tenant_id: int = 0,
    user_id: int | None = None,
    history: list[dict[str, Any]] | None = None,
    trace: Any = None,
    checkpointer: BaseCheckpointSaver | None = None,
    checkpoint_thread_id: str | None = None,
    llm_settings: Any = None,
    deadline: float | None = None,
    answer_language: str | None = None,
) -> dict[str, Any]:
    """Invoke the source-controlled LangGraph agent with request scope."""
    graph = (
        build_persistent_agent_graph(checkpointer)
        if checkpointer is not None
        else build_agent_graph()
    )
    config = None
    if checkpointer is not None:
        config = {
            "configurable": {
                "thread_id": checkpoint_thread_id or thread_id,
            }
        }

    state = graph.invoke(
        {
            "question": question,
            "company": company,
            "thread_id": thread_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "history": history or [],
        },
        config=config,
        context={
            "trace": trace,
            "llm_settings": llm_settings,
            "deadline": deadline,
            "answer_language": answer_language,
        },
        durability="sync" if checkpointer is not None else None,
    )
    return {
        "answer": state.get("answer", ""),
        "thread_id": thread_id,
        "tools_used": state.get("tools_used", []),
        "sources": state.get("sources", []),
        "citations": state.get("citations", []),
        "research_mode": state.get("research_mode", "default"),
        "evidence_count": state.get("evidence_count", 0),
        "plan": state.get("plan_summary", {}),
        "companies": state.get("companies", []),
        "research_plan": state.get("research_plan", []),
        "quality_score": state.get("quality_score", 0.0),
        "critique": state.get("critique", {}),
        "revision_count": state.get("revision_count", 0),
        "intent": state.get("intent", {}),
        "routing": state.get("routing"),
        "planning": state.get("planning"),
        "execution": state.get("execution"),
        "workflow": state.get("workflow"),
    }
