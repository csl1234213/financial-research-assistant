class UsageEvent:
    DOCUMENT_UPLOAD = "document_upload"
    DOCUMENT_PROCESS = "document_process"
    EMBEDDING_GENERATION = "embedding_generation"
    VECTOR_INSERT = "vector_insert"
    CHAT_REQUEST = "chat_request"
    LLM_TOKEN = "llm_token"
    AGENT_ASYNC_TASK = "agent_async_task"


class ResourceType:
    DOCUMENT = "document"
    CHUNK = "chunk"
    EMBEDDING = "embedding"
    VECTOR = "vector"
    CHAT = "chat"
    TOKEN = "token"
