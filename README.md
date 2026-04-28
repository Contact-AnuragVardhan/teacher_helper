# Teacher Helper

Teacher Helper is a FastAPI-based WhatsApp lesson-planning backend for Indian K-12 teachers. It supports a stable WhatsApp menu flow, NCERT-backed lesson planning, OpenAI-based generation with deterministic fallback, and teacher profile / lesson history management.

## Release 1 project details

- Facebook account name: **Ashley Pearson**
- Called phone number: **+1 (555) 142-5215**
- Release 1 commit / branch link: `Release-1`
- Project link: `https://github.com/Contact-AnuragVardhan/teacher_helper/tree/Release-1`

## Core menu flow

The current WhatsApp menu flow is:

- `1 → New Lesson`
- `2 → All Lessons`
- `3 → My Profile`

## Features

- WhatsApp-first lesson planning flow
- NCERT ingestion and retrieval
- Prompt assembly grounded in retrieved NCERT snippets
- OpenAI provider integration with deterministic fallback
- Teacher profile management
- Saved lesson retrieval through **All Lessons**
- Configurable duplicate lesson policy
- SQLite for local development, PostgreSQL-ready for deployment
- Structured logging
- Automated tests

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
- `OPENAI_API_KEY` if using OpenAI
- `LLM_PROVIDER`
- `DUPLICATE_LESSON_POLICY`
- `SESSION_TIMEOUT_MINUTES`

Useful optional variables:

- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `SUPPORTED_LANGUAGES`
- `LOG_LEVEL`
- `ALLOW_ORIGINS`
- `RESET_DB_ON_START`

## SQLite example

```env
DATABASE_URL="sqlite:///./teacher_helper.db"
LLM_PROVIDER="deterministic"
DUPLICATE_LESSON_POLICY="reject"
SESSION_TIMEOUT_MINUTES="30"
SUPPORTED_LANGUAGES="English,Hindi,Hinglish"
RESET_DB_ON_START=false
```

## PostgreSQL example

```env
DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/teacher_helper"
LLM_PROVIDER="openai"
OPENAI_API_KEY="your_api_key"
OPENAI_MODEL="gpt-4o-mini"
DUPLICATE_LESSON_POLICY="overwrite"
SESSION_TIMEOUT_MINUTES="45"
SUPPORTED_LANGUAGES="English,Hindi,Hinglish"
RESET_DB_ON_START=false
```

## Run the app

Start the server:

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

The project supports NCERT ingestion from local source data.

Expected fields per record:

- `grade`
- `subject`
- `chapter` (optional)
- `topic` (optional)
- `source_title`
- `content` or `content_chunk`
- `keywords` (optional)

If sample files are available in `sample_data/`, you can ingest them directly.

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
curl -X POST http://127.0.0.1:8000/webhook/whatsapp \
  -H "Content-Type: application/json" \
  -d '{"from": "+15551425215", "body": "1"}'
```

### Profile setup

```bash
curl -X POST http://127.0.0.1:8000/webhook/whatsapp \
  -H "Content-Type: application/json" \
  -d '{"from": "+15551425215", "body": "My Profile"}'
```

### Lesson generation API

```bash
curl -X POST http://127.0.0.1:8000/lesson/generate \
  -H "Content-Type: application/json" \
  -d '{
        "whatsapp_number": "+15551425215",
        "topic": "Plants",
        "duration_minutes": 35
      }'
```

## Behavioral notes

- The application uses the first value in `SUPPORTED_LANGUAGES` as the default language when a profile language is blank or missing. Use `English,Hindi,Hinglish` for English by default, or `Hindi,English,Hinglish` for Hindi by default.
- **All Lessons** is the current menu path for retrieving saved lessons.
- If `LLM_PROVIDER=openai` but no API key is configured, the app can still work through deterministic generation.
- If the LLM call fails, generation falls back to the deterministic provider automatically.
- Session inactivity beyond `SESSION_TIMEOUT_MINUTES` safely resets the conversation state to `MAIN_MENU`.
- For NCERT-matched topics, the generated lesson can include a `Source:` block based on the matched NCERT metadata.

## Release 1 handoff link

Project / release link:

`https://github.com/Contact-AnuragVardhan/teacher_helper/tree/Release-1`
