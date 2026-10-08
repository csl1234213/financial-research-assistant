from core.core_engine import run_rag


def display_citations(citations):

    print()

    print("=" * 60)

    print("EVIDENCE CITATIONS")

    print("=" * 60)

    print()

    for item in citations:

        print(

            f"Evidence {item['rank']}"

        )

        print(

            f"Source: {item['source']}"

        )

        print(

            f"Chunk ID: {item['chunk_id']}"

        )

        print(

            f"Similarity: {item['similarity']}"

        )

        print(

            "Preview:"
        )

        print(

            item["preview"]

        )

        print()

        print("-" * 60)


def get_user_question():

    print()

    question = input(

        "Ask a question (type 'exit' to quit):\n> "

    )

    return question


def display_result(answer):

    print()

    print("=" * 60)

    print("FINANCIAL ANALYSIS")

    print("=" * 60)

    print()

    print(answer)

    print()

    print("=" * 60)


if __name__ == "__main__":

    while True:
        q = input("> ")

        if q in ["exit", "quit"]:
            break

        answer, citations, context, mode, *_ = run_rag(q)

        print("\nMODE:", mode)
        print("\nANSWER:\n")
        print(answer)
