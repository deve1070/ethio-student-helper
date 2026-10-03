# Ethiopian student helper — data model & API contract

One backend serves three clients (web, Telegram bot, mobile app). This document defines the Postgres schema and the API contract everything else builds on.

## 1. Data model (Postgres)

Vector embeddings themselves live in Chroma/pgvector; this schema stores the relational data — users, entitlements, payments, and citation metadata that lets a vector `chunk_id` resolve into a real "Biology Gr.11, Unit 4, p.112" reference.

```sql
-- Users, shared across all three clients
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_number TEXT UNIQUE,          -- primary identifier; mobile money ties to phone
    email TEXT UNIQUE,
    full_name TEXT,
    grade_level SMALLINT,              -- 9-12, student's current grade
    password_hash TEXT,                -- null if the account is Telegram-only
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Links a Telegram account to a user (student may sign up on web, then link the bot)
CREATE TABLE telegram_links (
    telegram_user_id BIGINT PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    linked_at TIMESTAMPTZ DEFAULT now()
);

-- Mobile/web push tokens, for "your payment went through" notifications
CREATE TABLE devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    platform TEXT CHECK (platform IN ('ios','android','web')),
    push_token TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Textbook catalog
CREATE TABLE textbooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    grade SMALLINT NOT NULL CHECK (grade BETWEEN 9 AND 12),
    subject TEXT NOT NULL,
    title TEXT NOT NULL,
    edition_year SMALLINT,
    source_file_path TEXT,             -- original MoE PDF location
    created_at TIMESTAMPTZ DEFAULT now()
);

-- One row per retrievable chunk; mirrors vector store metadata so a
-- vector hit can resolve into a real citation
CREATE TABLE chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    textbook_id UUID REFERENCES textbooks(id) ON DELETE CASCADE,
    unit_or_chapter TEXT,
    section TEXT,
    page_start INT,
    page_end INT,
    text_excerpt TEXT,                 -- short excerpt for display, not the full chunk
    vector_id TEXT NOT NULL            -- id in Chroma/pgvector
);

-- Raw exam question submissions, before dedup against the canonical cache
CREATE TABLE exam_question_submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submitted_by UUID REFERENCES users(id),
    grade SMALLINT,
    subject TEXT,
    exam_year SMALLINT,
    raw_text TEXT,                     -- OCR'd or typed text
    image_path TEXT,                   -- original photo, if submitted as an image
    matched_question_id UUID,          -- filled in once deduped
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Canonical, deduplicated exam questions — the reusable cache
CREATE TABLE exam_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    grade SMALLINT,
    subject TEXT,
    exam_year SMALLINT,
    question_text TEXT NOT NULL,
    question_embedding_id TEXT,        -- id in vector store, used for similarity lookup
    times_asked INT DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Cached, verified answers to canonical exam questions
CREATE TABLE exam_answers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exam_question_id UUID REFERENCES exam_questions(id) ON DELETE CASCADE,
    answer_text TEXT NOT NULL,
    citation_chunk_ids UUID[],         -- references into chunks
    verification_status TEXT CHECK (verification_status IN ('auto_verified','needs_review','human_reviewed')),
    reviewed_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Credit ledger — balance = SUM(delta) per user, never store a running total
CREATE TABLE credit_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    delta INT NOT NULL,                -- positive = granted, negative = spent
    reason TEXT,                       -- 'purchase' | 'exam_solve_new' | 'exam_solve_cached' | 'free_daily_grant'
    related_exam_question_id UUID REFERENCES exam_questions(id),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Optional subscriptions, alongside or instead of pay-per-credit
CREATE TABLE subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    plan TEXT,                         -- e.g. 'monthly_unlimited_explain'
    status TEXT CHECK (status IN ('active','expired','cancelled')),
    current_period_end TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Payment transactions, gateway-agnostic
CREATE TABLE payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    gateway TEXT,                      -- 'chapa' | 'santimpay' | ...
    gateway_tx_ref TEXT UNIQUE,
    amount_etb NUMERIC(10,2),
    status TEXT CHECK (status IN ('initiated','pending','completed','failed','refunded')),
    credits_granted INT,
    created_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);
```

## 2. API contract

All endpoints are behind `/v1`. Auth is a bearer token issued at signup/login; the Telegram bot exchanges a Telegram user ID for a token via `/auth/telegram-link`, so the same token scheme works across all three clients.

### Auth
| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/auth/signup` | Create account (phone or email) |
| POST | `/v1/auth/login` | Returns bearer token |
| POST | `/v1/auth/telegram-link` | Links a `telegram_user_id` to a `user_id`, returns a token the bot caches |

### Content
| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/textbooks?grade=11&subject=Biology` | List available textbooks/units for a grade+subject picker |

### Explain mode
```
POST /v1/explain
{
  "grade": 11,
  "subject": "Biology",
  "question": "What is the difference between mitosis and meiosis?"
}

200 →
{
  "answer": "...",
  "citations": [
    {"textbook": "Biology Grade 11", "unit": "Unit 4", "page": "110-113"}
  ],
  "credits_charged": 0
}
```

### Exam-solver mode
```
POST /v1/exam/solve
{
  "grade": 12,
  "subject": "Physics",
  "exam_year": 2025,
  "question_text": "...",       // or image_base64 if submitted as a photo
}

200 →
{
  "exam_question_id": "uuid",
  "answer": "step-by-step explanation...",
  "citations": [...],
  "source": "cache" | "generated",
  "credits_charged": 0 | 1
}
```
Flow inside this endpoint: OCR if image → embed question text → similarity search against `exam_questions` → cache hit returns the stored `exam_answers` row (charges 0 or a reduced credit) → cache miss runs the full agent workflow, stores the new canonical question + answer, charges 1 credit.

### Entitlements & payments
| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/me/credits` | Current credit balance + active subscription status |
| POST | `/v1/payments/checkout` | Creates a gateway checkout session, returns a redirect URL |
| POST | `/v1/payments/webhook` | Gateway → backend callback (not client-facing); verifies signature, marks `payments.status = completed`, writes a `credit_ledger` grant |

Every paid endpoint (`/v1/exam/solve` past the free tier) checks `/v1/me/credits` server-side before running — never trust a client's local credit display.

## 3. Open decisions to settle before building

- Similarity threshold for exam-question cache matching (too loose → wrong cached answer served; too tight → cache barely helps)
- Whether cached answers cost fewer credits than freshly generated ones
- Daily free-tier cap for explain mode
- Chapa vs SantimPay vs ArifPay — fee/reliability comparison
- Android distribution: Play Store (Play Billing implications) vs direct APK

## 4. Suggested build order

1. Textbook ingestion pipeline + vector index (grade/subject filtered)
2. `/v1/explain` end-to-end on the web client only
3. Exam schema + `/v1/exam/solve` with cache lookup
4. Payments (`/v1/payments/checkout` + webhook) gated behind exam-solve
5. Telegram bot as a thin client against the same API
6. Mobile app (Flutter) last, once the API contract is stable

## 5. Project folder structure

A monorepo keeps the shared API contract visible to every client while they're built. Content (textbook PDFs, exam papers) stays out of version control — it's large, and MoE textbook redistribution is a licensing question you'll want to settle rather than something to solve by committing files to a repo.

```
ethio-student-helper/
├── backend/                         # FastAPI + LangGraph agent service (extends docchat)
│   ├── agents/
│   │   ├── relevance_checker.py
│   │   ├── research_agent.py
│   │   ├── citation_agent.py        # new: turns retrieved chunks into structured citations
│   │   └── verification_agent.py
│   ├── workflow.py                  # LangGraph graph definition
│   ├── ingestion/
│   │   ├── textbook_ingest.py       # batch job: MoE PDFs -> chunks -> vector index
│   │   ├── ocr.py                   # exam photo -> text
│   │   └── chunkers/
│   ├── retriever/
│   │   ├── textbook_retriever.py    # grade/subject filtered hybrid retriever
│   │   └── exam_cache_retriever.py  # similarity search over exam_questions
│   ├── payments/
│   │   ├── chapa_client.py
│   │   ├── webhook_handler.py
│   │   └── entitlement.py           # single guard fn every paid route calls
│   ├── db/
│   │   ├── models.py                # SQLAlchemy models matching section 1's schema
│   │   ├── migrations/              # Alembic
│   │   └── session.py
│   ├── api/
│   │   ├── routes_auth.py
│   │   ├── routes_explain.py
│   │   ├── routes_exam.py
│   │   ├── routes_payments.py
│   │   └── routes_textbooks.py
│   ├── config/
│   │   ├── settings.py
│   │   └── constants.py
│   ├── tests/
│   ├── requirements.txt
│   └── main.py                      # FastAPI app entrypoint
│
├── web/                              # web client
│   ├── src/
│   │   ├── pages/ (or app/)
│   │   ├── components/
│   │   └── api/                      # thin wrapper calling backend endpoints
│   ├── public/
│   └── package.json
│
├── telegram_bot/                     # thin client, python-telegram-bot
│   ├── handlers/
│   │   ├── explain_handler.py
│   │   ├── exam_handler.py
│   │   └── payment_handler.py
│   ├── bot.py
│   └── requirements.txt
│
├── mobile/                           # Flutter app
│   ├── lib/
│   │   ├── screens/
│   │   ├── services/                 # API client
│   │   └── main.dart
│   ├── android/
│   ├── ios/
│   └── pubspec.yaml
│
├── content/                          # NOT committed — .gitignore this whole folder
│   ├── moe_textbooks/
│   │   ├── grade_9/
│   │   ├── grade_10/
│   │   ├── grade_11/
│   │   └── grade_12/
│   └── past_exams/
│
├── docs/
│   ├── data-model-api.md             # this document
│   └── architecture.md
│
├── docker-compose.yml                 # local dev: postgres, chroma, backend
└── README.md
```

Each client folder (`web/`, `telegram_bot/`, `mobile/`) only ever talks to `backend/api/` — none of them touch the database, vector store, or payment gateway directly. That's what keeps the "one backend, three clients" design from section 2 actually true in the codebase, not just on paper.
