"""Required vector/text/metadata readback gate, independent of query runtime."""
import math


class IndexBuildIntegrityEvaluator:
    def evaluate(self, vector_store, collection, documents):
        stored = vector_store.client.get_collection(collection)
        result = stored.get(ids=[doc.chunk_id for doc in documents],
                            include=["documents", "metadatas", "embeddings"])
        actual = {identifier: (text, metadata, vector) for identifier, text, metadata, vector in
                  zip(result["ids"], result["documents"], result["metadatas"], result["embeddings"])}
        if stored.count() != len(documents) or any(
            doc.chunk_id not in actual or actual[doc.chunk_id][0] != doc.content
            or any(actual[doc.chunk_id][1].get(key) != value for key, value in doc.metadata.items())
            or len(actual[doc.chunk_id][2]) != len(doc.embedding)
            or any(not math.isclose(float(stored_value), expected, rel_tol=1e-6, abs_tol=1e-7)
                   for stored_value, expected in zip(actual[doc.chunk_id][2], doc.embedding))
            for doc in documents
        ):
            raise ValueError("INDEX_READBACK_FAILED")
        return len(documents)
