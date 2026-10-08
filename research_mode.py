COMPARE_KEYWORDS = [

    "compare",
    "comparison",
    "vs",
    "versus",
    "difference",
    "better",
    "stronger",
    "weaker",
    "larger",
    "smaller",
    "advantage",
    "leading",
    "leader"

]

def detect_research_mode(question):
    q = question.lower()
    research_modes = {

        "compare": [
            "compare",
            "comparison",
            "vs",
            "versus",
            "difference"
        ],

        "leader": [
            "stronger",
            "leader",
            "leading",
            "best",
            "largest",
            "dominant",
            "moat"
        ],

        "risk": [
            "risk",
            "challenge",
            "threat",
            "weakness"
        ],

        "growth": [
            "growth",
            "future",
            "opportunity",
            "expand"
        ],

        "investment": [
            "investment",
            "invest",
            "buy",
            "position",
            "outlook"
        ]

    }
    for mode, keywords in research_modes.items():
        for keyword in keywords:
            if keyword in q:
                return mode
    return "default"

