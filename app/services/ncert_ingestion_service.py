import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger, log_event
from app.models.ncert_content import NcertContent
from app.repositories.ncert_repository import NcertContentRepository

logger = get_logger(__name__)


@dataclass(slots=True)
class IngestionSummary:
    files_processed: int
    records_processed: int
    chunks_created: int


class NcertIngestionService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = NcertContentRepository(db)
        self.settings = get_settings()

    def ingest_path(self, path: str | Path, truncate_first: bool = False) -> IngestionSummary:
        input_path = Path(path)
        if not input_path.exists():
            raise FileNotFoundError(f"Path not found: {input_path}")

        if truncate_first:
            self.repo.truncate()
            log_event(logger, "ncert_truncate", path=str(input_path))

        files = [input_path] if input_path.is_file() else sorted(
            p for p in input_path.rglob("*") if p.is_file() and p.suffix.lower() in {".json", ".csv"}
        )

        total_records = 0
        total_chunks = 0
        for file_path in files:
            raw_records = self._read_records(file_path)
            rows = self._normalize_records(raw_records)
            if rows:
                self.repo.bulk_create(rows)
            total_records += len(raw_records)
            total_chunks += len(rows)
            log_event(
                logger,
                "ncert_ingest_file",
                path=str(file_path),
                records=len(raw_records),
                chunks=len(rows),
            )

        return IngestionSummary(
            files_processed=len(files),
            records_processed=total_records,
            chunks_created=total_chunks,
        )

    def _read_records(self, file_path: Path) -> list[dict]:
        suffix = file_path.suffix.lower()
        if suffix == ".json":
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload = payload.get("records", [])
            if not isinstance(payload, list):
                raise ValueError(f"JSON file must contain a list of records: {file_path}")
            return [self._normalize_dict(record) for record in payload]

        if suffix == ".csv":
            with file_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                return [self._normalize_dict(row) for row in reader]

        raise ValueError(f"Unsupported file type: {file_path}")

    def _normalize_dict(self, row: dict) -> dict:
        return {str(key).strip(): value for key, value in row.items()}

    def _normalize_records(self, records: list[dict]) -> list[NcertContent]:
        rows: list[NcertContent] = []
        for record in records:
            grade = self._clean(record.get("grade"))
            subject = self._clean(record.get("subject"))
            chapter = self._clean(record.get("chapter")) or None
            topic = self._clean(record.get("topic")) or None
            source_title = self._clean(record.get("source_title"))
            content = self._clean(record.get("content_chunk") or record.get("content"))
            keywords = self._keywords_string(record, grade, subject, chapter, topic, source_title, content)

            if not grade or not subject or not source_title or not content:
                raise ValueError(
                    "Each NCERT record must include grade, subject, source_title, and content/content_chunk."
                )

            for chunk in self._chunk_text(content):
                rows.append(
                    NcertContent(
                        grade=grade,
                        subject=subject,
                        chapter=chapter,
                        topic=topic,
                        source_title=source_title,
                        content_chunk=chunk,
                        keywords=keywords,
                    )
                )
        return rows

    def _clean(self, value: object) -> str:
        return str(value or "").strip()

    def _keywords_string(
        self,
        record: dict,
        grade: str,
        subject: str,
        chapter: str | None,
        topic: str | None,
        source_title: str,
        content: str,
    ) -> str:
        explicit = self._clean(record.get("keywords"))
        tokens: list[str] = []
        if explicit:
            tokens.extend(re.split(r"[,;|]", explicit))
        tokens.extend([grade, subject, chapter or "", topic or "", source_title])
        tokens.extend(re.findall(r"[A-Za-z][A-Za-z0-9-]+", content)[:20])
        deduped: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            cleaned = token.strip()
            if not cleaned:
                continue
            lowered = cleaned.casefold()
            if lowered in seen:
                continue
            seen.add(lowered)
            deduped.append(cleaned)
        return ", ".join(deduped)

    def _chunk_text(self, content: str) -> list[str]:
        max_chars = self.settings.ncert_chunk_size
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
        if not paragraphs:
            paragraphs = [content.strip()]

        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
            if len(candidate) <= max_chars:
                current = candidate
                continue
            if current:
                chunks.append(current)
            if len(paragraph) <= max_chars:
                current = paragraph
                continue

            sentence_buffer = ""
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                piece = f"{sentence_buffer} {sentence}".strip() if sentence_buffer else sentence
                if len(piece) <= max_chars:
                    sentence_buffer = piece
                else:
                    if sentence_buffer:
                        chunks.append(sentence_buffer)
                    sentence_buffer = sentence
            current = sentence_buffer

        if current:
            chunks.append(current)

        return [chunk for chunk in chunks if chunk.strip()]
