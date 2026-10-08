# core/citation_formatter.py


def format_citations(citations):
    lines = []

    lines.append("")
    lines.append("Evidence References")
    lines.append("=" * 60)

    for item in citations:
        lines.append(f"[Evidence {item['rank']}]")

        lines.append(f"Source: {item['source']}")

        lines.append(f"Chunk: {item['chunk_id']}")

        lines.append(f"Confidence: {item['similarity']}")

        lines.append("")

        lines.append("Preview:")

        lines.append(item["preview"])

        lines.append("")
        lines.append("-" * 60)

    return "\n".join(lines)
