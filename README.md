# Ethiopian Student Helper

## Layout
- `backend/` — FastAPI service (extends the original docchat prototype). Everything else calls this; it's the only thing that touches Postgres, Chroma, and the payment gateway.
- `telegram_bot/` — thin Telegram client. Calls `backend/` over HTTP via `telegram_bot/api_client.py`.
- `docs/data-model-api.md` — schema, API contract, folder structure, and open decisions.

## Providers
LLM generation runs on **Groq** (fast, free tier) and embeddings on **Gemini's text-embedding-004** (Groq doesn't serve embedding models). Get free keys at console.groq.com and aistudio.google.com. See `backend/.env.example` for every environment variable the backend needs.

## Getting the backend running
```
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in GROQ_API_KEY, GEMINI_API_KEY, DATABASE_URL, etc.
uvicorn main:app --reload
```

Textbook ingestion (once you have MoE PDFs under `backend/content/moe_textbooks/grade_<N>/<subject>/`):
```
python -m ingestion.textbook_ingest
```

## Getting the Telegram bot running
```
cd telegram_bot
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=...      # from @BotFather
export BACKEND_BASE_URL=http://localhost:8000
python -m bot
```

## What's implemented so far
- `POST /v1/explain` — grounded, cited textbook explanations, scoped to grade + subject
- `POST /v1/exam/solve` — cache-first exam question solving (text or photo), with citations
- `POST /v1/auth/signup|login|telegram-link` — one auth system across every client
- `POST /v1/payments/checkout|webhook`, `GET /v1/me/credits` — Chapa checkout, signature-verified webhook, credit ledger
- Telegram bot: `/login`, `/explain`, `/exam`, `/credits`, `/buy`

## Known open items
See `docs/data-model-api.md` section 3, plus inline comments flagged throughout the code:
- Exam-cache similarity threshold is a placeholder, untuned
- Credit bundle pricing is a placeholder
- No auth rate limiting or password reset yet
- Web app and mobile app clients not started yet
