from core_engine import run_rag
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()


@app.post("/chat_stream")
def chat_stream(req: dict):

    def generate():

        answer, citations, context, mode, *_ = run_rag(req["question"])

        for char in answer:
            yield char

    return StreamingResponse(generate(), media_type="text/plain")
