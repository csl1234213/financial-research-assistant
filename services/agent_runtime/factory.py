import logging

logger = logging.getLogger(__name__)

_LANGGRAPH_AGENT = None


def get_agent_graph():
    global _LANGGRAPH_AGENT

    if _LANGGRAPH_AGENT is not None:
        return _LANGGRAPH_AGENT

    try:
        from services.agent_runtime.graph import build_agent_graph, run_agent

        _LANGGRAPH_AGENT = {"build_agent_graph": build_agent_graph, "run_agent": run_agent}
        return _LANGGRAPH_AGENT
    except ImportError as e:
        logger.error(f"Failed to import the source-controlled LangGraph agent: {e}")
        _LANGGRAPH_AGENT = False
        return False


def is_agent_available() -> bool:
    return get_agent_graph() is not False
