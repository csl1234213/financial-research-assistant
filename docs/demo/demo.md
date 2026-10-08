# Demo Showcase

## Screenshots to Capture

### 1. Swagger API Health (`docs/images/swagger_health.png`)

1. Start the server: `uvicorn api.main:app --reload`
2. Open `http://127.0.0.1:8000/docs`
3. Execute `GET /api/v1/health`
4. Capture the response showing `APP_VERSION: "8.2.0"`

### 2. Direct Chat Demo (`docs/images/direct_chat_demo.png`)

1. In Swagger UI, execute `POST /api/v1/chat`
2. Request body:
```json
{
  "question": "What is AI?",
  "stream": false
}
```
3. Capture the response showing:
   - `workflow.type: "direct_chat"`
   - `execution.use_retrieval: false`
   - `routing.provider: "deepseek"`

### 3. RAG Demo (`docs/images/tesla_rag_demo.png`)

1. Upload a Tesla financial PDF via `POST /api/v1/upload`
2. Execute `POST /api/v1/chat` with:
```json
{
  "question": "Analyze Tesla revenue growth",
  "stream": false
}
```
3. Capture the response showing:
   - `workflow.type: "rag"`
   - `citations` with multiple entries
   - `evidence` with source documents
   - `report` containing "# Research Report"

### 4. Architecture Diagram

The Mermaid diagram in README.md is rendered automatically by GitHub.

---

## Demo Script

### Direct Chat Flow

```
User: Hello
  → Intent: DIRECT_CHAT
  → Workflow: direct_chat
  → Provider: DeepSeek
  → Response: conversational answer
  → No retrieval, no citations
```

### RAG Research Flow

```
User: Analyze Tesla revenue growth
  → Intent: SINGLE_COMPANY
  → Workflow: rag
  → Strategy: RAG
  → Retrieval: semantic search + ranking
  → Context: evidence + citations
  → Provider: DeepSeek
  → Response: Research Report with evidence
```
