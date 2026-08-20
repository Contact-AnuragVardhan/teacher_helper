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
- `4 → Feedback`
- `5 → ADMIN`

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
- Generated lesson export to PDF and delivery as a WhatsApp document
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
- `ADMIN_PASSWORD` (exactly 4 digits)
- `ADMIN_TEACHERS` (comma-separated WhatsApp numbers allowed in ADMIN reports)
- `ADMIN_REPORT_TIMEZONE` (defaults to `Asia/Kolkata`)

Useful optional variables:

- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `SUPPORTED_LANGUAGES`
- `LOG_LEVEL`
- `ALLOW_ORIGINS`
- `RESET_DB_ON_START`
- `LESSON_PDF_FONT_PATH` and `LESSON_PDF_BOLD_FONT_PATH` when system fonts are unavailable
- `LESSON_PDF_DEVANAGARI_FONT_PATH` and `LESSON_PDF_DEVANAGARI_BOLD_FONT_PATH` for Hindi PDF output

## SQLite example

```env
DATABASE_URL="sqlite:///./teacher_helper.db"
LLM_PROVIDER="deterministic"
DUPLICATE_LESSON_POLICY="reject"
SESSION_TIMEOUT_MINUTES="30"
ADMIN_PASSWORD="9876"
ADMIN_TEACHERS="+916291687879,+919009653018,+919691437223"
ADMIN_REPORT_TIMEZONE="Asia/Kolkata"
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
ADMIN_PASSWORD="9876"
ADMIN_TEACHERS="+916291687879,+919009653018,+919691437223"
ADMIN_REPORT_TIMEZONE="Asia/Kolkata"
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

## ADMIN usage and feedback reporting

The top-level WhatsApp menu includes `ADMIN`. The password is read only from `ADMIN_PASSWORD`. Teacher choices are restricted to the WhatsApp numbers in `ADMIN_TEACHERS`; names and other display details are read from the existing `teacher_profile` rows. Then choose:

1. **Teacher Usage** — select a teacher by name, then one of exactly four Sunday-start weeks: the current week plus the previous three. The report shows Sunday through Saturday with total tracked chat minutes for each day. Chat sessions are separated using `SESSION_TIMEOUT_MINUTES`; a one-message session counts as one minute.
2. **Teacher Feedback** — select a teacher and one of the same four weeks. The report shows saved feedback answers only, one answer per line, without repeating the survey questions.
3. **Exit** — returns to the normal Teacher Helper main menu.

Usage timestamps are stored in `teacher_chat_activity`; message text is not stored for usage reporting. Existing feedback continues to use `feedback_submission`. Days older than the first tracked/backfilled activity are displayed as `Not tracked`, not as a false zero.

The old `session_state` cannot reconstruct historical chat duration because it stores only the latest session update. If hosting/application logs were retained, backfill the new table from `conversation_inbound` log events. For the current week of August 16-22, 2026, for example:

```bash
python scripts/backfill_teacher_chat_activity_from_logs.py \
  --log-file render-teacher-helper.log \
  --from-date 2026-08-16 \
  --to-date 2026-08-22 \
  --dry-run

# If the count looks correct, rerun without --dry-run.
```

The backfill ignores teachers not present in `ADMIN_TEACHERS` and avoids exact timestamp duplicates. The retained log lines must contain a timestamp (for example the Render timestamp prefix).

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

## Post-generation lesson actions and page customization

After a detailed day lesson is generated, Teacher Helper displays:

1. **Use this lesson** — opens the existing Save Lesson / Cancel / Main Menu flow.
2. **Customize Lesson** — starts the direct page-range customization flow.
3. **Print Lesson** — generates a formatted PDF from the current lesson, sends it to the teacher as a WhatsApp document, and shows the same action menu again.

The direct customization sequence is:

```text
Customize Lesson
→ Ask From Book Page
→ Ask To Book Page
→ Validate the contiguous chapter range
→ Retrieve only those book pages
→ Regenerate the lesson automatically
→ Show Use this lesson / Customize Lesson / Print Lesson again
```

The From Book Page prompt displays the current lesson book-page range and the complete selected TOC item's book-page range. After a valid From Book Page is entered, Teacher Helper asks for To Book Page. Entering a valid To Book Page immediately regenerates the lesson; there is no additional Create/Save menu selection.

Teacher-facing page input and output use printed **book pages only**, including compound labels such as `2/4`. Physical PDF page numbers are internal retrieval coordinates only: inputs such as `PDF 21` are intentionally rejected, and numeric input never falls back to a physical PDF page.

Page customization reads only from `embeddings_page_extractions`. The selected book pages must:

- belong to the selected TOC item;
- map to an inclusive, contiguous source-page sequence internally; and
- contain usable extracted text.

After regeneration, **Use this lesson** continues through the existing save and lesson-name flow. Customized lesson names automatically receive a trailing `*`, and saved source metadata records `source_type=pdf_to_embeddings_page_range`, the selected book-page range, and `is_customized=true`.

Existing profile, language, lesson-list, save/cancel, share, delete, post-generation action, and Main Menu behavior remains available.


## TOC terminology and greeting-to-home behavior

Teacher Helper no longer assumes that every row in `embeddings_book_chapters` is a user-facing chapter. It derives the displayed TOC type from `structure_type` and the source fields: chapters/prose are shown as **Chapter**, poems/poetry/lessons as **Lesson**, and section/unit/topic records keep their own terminology. Generic selection screens say **Book TOC** so mixed books do not promote lessons or poems to chapters.

`Hi`, `Hello`, `Namaste`, `Namaskar`, `Pranam`, common variants such as `Hii`, and greeting-led messages such as `Hello teacher` are global home commands. They reset the active conversation flow and return the teacher to the Main Menu from any state.

## Print Lesson PDF export

Selecting **Print Lesson** exports the currently generated lesson, including a customized lesson, without requiring the teacher to save it first. The PDF contains teacher, school, grade, subject, duration, book, TOC item type/title, day, selected book-page range, customization status, the full lesson plan, and page numbers.

Delivery uses the WhatsApp Cloud API in two steps:

1. Upload the generated `application/pdf` file to `/{PHONE_NUMBER_ID}/media`.
2. Send a document message using the returned media ID, then send the existing Use / Customize / Print buttons again.

The generated file is kept in memory only; the application does not need a persistent PDF folder. Mock webhook responses omit the base64 PDF body so test responses remain small.

For Hindi PDFs, install the dependencies from `requirements.txt` and ensure a Devanagari font is available. The application checks common Noto Sans Devanagari locations and also supports explicit font paths through the `LESSON_PDF_*` environment variables. Font files are not included in this project archive.


## Optional teacher weekly schedules

Teacher Helper can now read the additive `embeddings_teacher_schedules` and
`embeddings_teacher_schedule_days` tables created by the JSON-to-DB project.
This does **not** replace `embeddings_book_subsections`.

Behavior is intentionally backward compatible:

- If the selected TOC item has no teacher schedule rows, the existing structural
  `Day 1 / Day 2 / ...` subsection flow is used unchanged.
- If exactly one teacher schedule exists, Teacher Helper goes directly to its
  Monday-Friday day list.
- If multiple schedules exist for the same chapter, the teacher first chooses
  the week/exercise and then chooses the day.
- Scheduled days retrieve the exact `selected_pdf_pages` / `selected_book_pages`
  from `embeddings_page_extractions`. Non-contiguous source selections are kept
  exact; missing intermediate pages are not silently added.
- Exercise, assigned question IDs, schedule topic/activity, week, and exact book
  pages are passed to lesson generation as mandatory schedule context.
- Page customization remains the existing teacher-entered contiguous From/To
  Book Page flow. When customization starts from a scheduled lesson, its
  exercise/question target is preserved while the teacher-selected page range
  becomes the source text.
- If the new schedule tables are not installed yet or a chapter has no schedule,
  Teacher Helper falls back safely to the original subsection flow.
