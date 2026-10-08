from collections import Counter


def analyze_evidence(citations):
    source_counter = Counter()

    for c in citations:
        source_counter[c["source"]] += 1

    return dict(source_counter)
