from typing import Any, Dict, Optional


def calculate_cost(
    token_usage: Optional[Dict[str, int]] = None,
    duration_seconds: float = 0.0,
    tool_calls: int = 0,
) -> Dict[str, Any]:
    input_tokens = (token_usage or {}).get("input_tokens", 0)
    output_tokens = (token_usage or {}).get("output_tokens", 0)
    total_tokens = (token_usage or {}).get("total_tokens", input_tokens + output_tokens)

    if total_tokens == 0 and input_tokens + output_tokens > 0:
        total_tokens = input_tokens + output_tokens

    input_cost = (input_tokens / 1000) * 0.0015
    output_cost = (output_tokens / 1000) * 0.006
    tool_cost = tool_calls * 0.001

    total_cost = input_cost + output_cost + tool_cost
    total_cost = round(total_cost, 6)

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "input_cost": round(input_cost, 6),
        "output_cost": round(output_cost, 6),
        "tool_cost": round(tool_cost, 6),
        "total_cost": total_cost,
        "currency": "USD",
    }
