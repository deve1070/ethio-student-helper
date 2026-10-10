"""
FastAPI entrypoint for the production backend. This is the single service
that the web app, Telegram bot, and mobile app all call — none of them
talk to the database, vector store, or agents directly.

app.py's Gradio UI is left in place as a local debugging tool for the
underlying retriever/agent logic; it is not part of the production path.

Run with: uvicorn main:app --reload
"""

from fastapi import FastAPI

from api.routes_auth import router as auth_router
from api.routes_exam import router as exam_router
from api.routes_explain import router as explain_router
from api.routes_payments import router as payments_router
from api.routes_practice import router as practice_router

app = FastAPI(title="Ethiopian Student Helper API", version="0.1.0")

app.include_router(auth_router)
app.include_router(explain_router)
app.include_router(practice_router)
# app.include_router(exam_router)
# app.include_router(payments_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
