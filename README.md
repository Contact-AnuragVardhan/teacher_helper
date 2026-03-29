# Teacher Helper

Teacher Helper is a FastAPI-based WhatsApp lesson-planning backend that keeps the core menu flow stable:

- `1 → New Lesson`
- `2 → My Lessons`
- `3 → My Profile`

The backend stays monolithic and maintainable while providing:

- deterministic NCERT ingestion and retrieval
- prompt assembly grounded in retrieved NCERT snippets
- LLM provider abstraction with deterministic fallback
- configurable duplicate lesson policy
- SQLite + PostgreSQL readiness
- structured logging
- broader automated tests

## Requirements

- Python 3.12
- SQLite for local development, or PostgreSQL for pilot/demo deployment

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

## Environment variables

Minimal variables:

- `DATABASE_URL`
- `OPENAI_API_KEY`
- `LLM_PROVIDER`
- `DUPLICATE_LESSON_POLICY`
- `SESSION_TIMEOUT_MINUTES`

Useful optional variables:

- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `SUPPORTED_LANGUAGES`
- `LOG_LEVEL`
- `ALLOW_ORIGINS`

## SQLite example

```env
DATABASE_URL="sqlite:///./teacher_helper.db"
LLM_PROVIDER="deterministic"
DUPLICATE_LESSON_POLICY="reject"
SESSION_TIMEOUT_MINUTES="30"
SUPPORTED_LANGUAGES="English"
```

## PostgreSQL example

```env
DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/teacher_helper"
LLM_PROVIDER="openai"
OPENAI_API_KEY="your_api_key"
OPENAI_MODEL="gpt-4o-mini"
DUPLICATE_LESSON_POLICY="overwrite"
SESSION_TIMEOUT_MINUTES="45"
SUPPORTED_LANGUAGES="English"
```

## Run the app

Then start the server:

```bash
uvicorn app.main:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## Database setup

The app creates tables automatically on startup.

Use this for a clean reset-from-scratch workflow during development:

```env
RESET_DB_ON_START=true
```

Use this to keep existing data and only create missing tables:

```env
RESET_DB_ON_START=false
```


## NCERT ingestion

Place source files in a local folder. JSON and CSV are both supported.

Expected fields per record:

- `grade`
- `subject`
- `chapter` (optional)
- `topic` (optional)
- `source_title`
- `content` or `content_chunk`
- `keywords` (optional)

Sample files are included in `sample_data/`.

Ingest a single file:

```bash
python scripts/ingest_ncert.py --file sample_data/ncert_grade5_science.json
```

Ingest a folder recursively:

```bash
python scripts/ingest_ncert.py --dir sample_data
```

Clear previously ingested content first:

```bash
python scripts/ingest_ncert.py --dir sample_data --truncate-first
```

## Running tests

```bash
pytest
```

## Sample webhook payloads

### Main menu

```bash
curl -X POST http://127.0.0.1:8000/webhook/whatsapp   -H "Content-Type: application/json"   -d '{"from": "+15550001111", "body": "1"}'
```

### Profile setup

```bash
curl -X POST http://127.0.0.1:8000/webhook/whatsapp   -H "Content-Type: application/json"   -d '{"from": "+15550001111", "body": "My Profile"}'
```

### Lesson generation API

```bash
curl -X POST http://127.0.0.1:8000/lesson/generate   -H "Content-Type: application/json"   -d '{
        "whatsapp_number": "+15550001111",
        "topic": "Plants",
        "duration_minutes": 35
      }'
```

## Behavioral notes

- Preferred language stays English-only unless `SUPPORTED_LANGUAGES` is explicitly broadened.
- `My Lessons` still uses exact lesson-name retrieval for the current teacher.
- If `LLM_PROVIDER=openai` but no API key is configured, the app still works through deterministic generation.
- If the LLM call fails, generation falls back to the deterministic provider automatically.
- Session inactivity beyond `SESSION_TIMEOUT_MINUTES` safely resets the conversation state to `MAIN_MENU`.
