import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
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

    def ingest_path(
        self,
        path: str | Path,
        truncate_first: bool = False,
        include_supplementary: bool = False,
    ) -> IngestionSummary:
        input_path = Path(path)
        if not input_path.exists():
            log_event(logger, "ncert_ingest_path_missing", path=str(input_path))
            raise FileNotFoundError(f"Path not found: {input_path}")

        if truncate_first:
            self.repo.truncate()
            logger.info("TRUNCATED existing NCERT content | path=%s", input_path)

        total_files_processed = 0
        total_records = 0
        total_chunks = 0

        if input_path.is_file():
            if input_path.suffix.lower() not in {".json", ".csv"}:
                raise ValueError("Single-file ingestion supports only JSON or CSV files.")

            raw_records = self._read_records(input_path)
            grade, subject, book = self._derive_processing_context(raw_records, input_path)

            logger.info(
                "START FILE | grade=%s | subject=%s | book=%s | file=%s",
                grade or "-",
                subject or "-",
                book or input_path.stem,
                input_path,
            )

            rows, skipped_non_english = self._normalize_records(raw_records)

            if rows:
                self.repo.bulk_create(rows)

            total_files_processed = 1
            total_records = len(raw_records)
            total_chunks = len(rows)

            logger.info(
                "DONE FILE  | grade=%s | subject=%s | book=%s | file=%s | records=%s | inserted_chunks=%s | skipped_non_english=%s",
                grade or "-",
                subject or "-",
                book or input_path.stem,
                input_path,
                len(raw_records),
                len(rows),
                skipped_non_english,
            )

            return IngestionSummary(
                files_processed=total_files_processed,
                records_processed=total_records,
                chunks_created=total_chunks,
            )

        structured_files = sorted(
            p for p in input_path.rglob("*") if p.is_file() and p.suffix.lower() in {".json", ".csv"}
        )
        book_dirs = self._discover_book_dirs(input_path)

        logger.info(
            "NCERT INGEST STARTED | path=%s | structured_files=%s | book_dirs=%s | truncate_first=%s | include_supplementary=%s",
            input_path,
            len(structured_files),
            len(book_dirs),
            truncate_first,
            include_supplementary,
        )

        for file_path in structured_files:
            raw_records = self._read_records(file_path)
            grade, subject, book = self._derive_processing_context(raw_records, file_path)

            logger.info(
                "START FILE | grade=%s | subject=%s | book=%s | file=%s",
                grade or "-",
                subject or "-",
                book or file_path.stem,
                file_path,
            )

            rows, skipped_non_english = self._normalize_records(raw_records)

            if rows:
                self.repo.bulk_create(rows)

            total_files_processed += 1
            total_records += len(raw_records)
            total_chunks += len(rows)

            logger.info(
                "DONE FILE  | grade=%s | subject=%s | book=%s | file=%s | records=%s | inserted_chunks=%s | skipped_non_english=%s",
                grade or "-",
                subject or "-",
                book or file_path.stem,
                file_path,
                len(raw_records),
                len(rows),
                skipped_non_english,
            )

        for book_dir in book_dirs:
            summary = self.ingest_book_directory(
                root_path=input_path,
                book_dir=book_dir,
                include_supplementary=include_supplementary,
            )
            total_files_processed += summary.files_processed
            total_records += summary.records_processed
            total_chunks += summary.chunks_created

        if total_files_processed == 0 and total_records == 0:
            raise ValueError(
                "No ingestible content found. Expected JSON/CSV files or book folders containing url.txt and chapter PDFs."
            )

        logger.info(
            "NCERT INGEST COMPLETED | path=%s | files_processed=%s | records_processed=%s | chunks_created=%s",
            input_path,
            total_files_processed,
            total_records,
            total_chunks,
        )

        return IngestionSummary(
            files_processed=total_files_processed,
            records_processed=total_records,
            chunks_created=total_chunks,
        )

    def ingest_book_directory(
        self,
        *,
        root_path: str | Path,
        book_dir: str | Path,
        include_supplementary: bool = False,
    ) -> IngestionSummary:
        resolved_root_path = Path(root_path)
        resolved_book_dir = Path(book_dir)

        if not resolved_root_path.exists():
            raise FileNotFoundError(f"Root path not found: {resolved_root_path}")
        if not resolved_book_dir.exists():
            raise FileNotFoundError(f"Book directory not found: {resolved_book_dir}")

        rel_parts = resolved_book_dir.relative_to(resolved_root_path).parts
        grade = self._normalize_grade(rel_parts[0]) if len(rel_parts) >= 1 else None
        subject = rel_parts[1].strip() if len(rel_parts) >= 2 else None
        book = resolved_book_dir.name.strip()

        logger.info(
            "START BOOK | grade=%s | subject=%s | book=%s | path=%s",
            grade or "-",
            subject or "-",
            book or "-",
            resolved_book_dir,
        )

        raw_records, pdf_count = self._read_book_directory_records(
            root_path=resolved_root_path,
            book_dir=resolved_book_dir,
            include_supplementary=include_supplementary,
        )
        rows, skipped_non_english = self._normalize_records(raw_records)

        if rows:
            self.repo.bulk_create(rows)

        logger.info(
            "DONE BOOK  | grade=%s | subject=%s | book=%s | pdf_files=%s | records=%s | inserted_chunks=%s | skipped_non_english=%s",
            grade or "-",
            subject or "-",
            book or "-",
            pdf_count,
            len(raw_records),
            len(rows),
            skipped_non_english,
        )

        return IngestionSummary(
            files_processed=pdf_count,
            records_processed=len(raw_records),
            chunks_created=len(rows),
        )

    def _discover_book_dirs(self, root_path: Path) -> list[Path]:
        book_dirs = {url_file.parent for url_file in root_path.rglob("url.txt")}
        return sorted(book_dirs)

    def _read_book_directory_records(
        self,
        *,
        root_path: Path,
        book_dir: Path,
        include_supplementary: bool,
    ) -> tuple[list[dict], int]:
        rel_parts = book_dir.relative_to(root_path).parts

        if len(rel_parts) < 3:
            logger.warning(
                "SKIP BOOK DIR | path=%s | reason=%s",
                book_dir,
                "expected at least Grade/Subject/.../BookName structure",
            )
            return [], 0

        grade = self._normalize_grade(rel_parts[0])
        subject = rel_parts[1].strip()
        book = book_dir.name.strip()
        book_url = self._read_book_url(book_dir)

        pdf_paths = sorted(p for p in book_dir.glob("*.pdf"))
        records: list[dict] = []
        processed_pdf_count = 0

        for pdf_path in pdf_paths:
            logger.info(
                "START PDF  | grade=%s | subject=%s | book=%s | pdf=%s",
                grade,
                subject,
                book,
                pdf_path.name,
            )

            full_text, first_page_text = self._extract_pdf_text(pdf_path)
            if not full_text.strip():
                logger.warning(
                    "SKIP PDF   | grade=%s | subject=%s | book=%s | pdf=%s | reason=empty_text",
                    grade,
                    subject,
                    book,
                    pdf_path.name,
                )
                continue

            if not include_supplementary and self._looks_like_supplementary(pdf_path, first_page_text):
                logger.info(
                    "SKIP PDF   | grade=%s | subject=%s | book=%s | pdf=%s | reason=supplementary",
                    grade,
                    subject,
                    book,
                    pdf_path.name,
                )
                continue

            chapter, unit_name, topic_name = self._infer_pdf_labels(first_page_text, pdf_path)
            topic_summary = self._build_topic_summary(full_text, topic_name)
            lesson_goal = self._build_lesson_goal(subject, topic_name, book)

            records.append(
                {
                    "grade": grade,
                    "subject": subject,
                    "book": book,
                    "book_url": book_url,
                    "chapter": chapter,
                    "topic": topic_name,
                    "unit_name": unit_name,
                    "topic_name": topic_name,
                    "topic_summary": topic_summary,
                    "lesson_goal": lesson_goal,
                    "source_reference": book_url or f"{subject}/{book}",
                    "source_title": f"{book} - {topic_name or pdf_path.stem}",
                    "content": full_text,
                    "keywords": ", ".join(
                        filter(
                            None,
                            [
                                grade,
                                subject,
                                book,
                                chapter or "",
                                unit_name or "",
                                topic_name or "",
                                pdf_path.stem,
                            ],
                        )
                    ),
                }
            )
            processed_pdf_count += 1

            logger.info(
                "DONE PDF   | grade=%s | subject=%s | book=%s | pdf=%s | chapter=%s | topic=%s",
                grade,
                subject,
                book,
                pdf_path.name,
                chapter or "-",
                topic_name or "-",
            )

        return records, processed_pdf_count

    def _read_book_url(self, book_dir: Path) -> str | None:
        url_file = book_dir / "url.txt"
        if not url_file.exists():
            return None
        try:
            first_line = url_file.read_text(encoding="utf-8").splitlines()[0].strip()
            return first_line or None
        except Exception as exc:
            log_event(logger, "ncert_book_url_read_failed", path=str(url_file), error=str(exc))
            return None

    def _extract_pdf_text(self, pdf_path: Path) -> tuple[str, str]:
        try:
            reader = PdfReader(str(pdf_path))
            page_texts: list[str] = []
            for page in reader.pages:
                page_text = page.extract_text() or ""
                page_text = page_text.replace("\x00", " ")
                page_text = re.sub(r"[ \t]+\n", "\n", page_text)
                page_text = re.sub(r"\n{3,}", "\n\n", page_text)
                page_text = re.sub(r"[ \t]{2,}", " ", page_text)
                cleaned = page_text.strip()
                if cleaned:
                    page_texts.append(cleaned)

            full_text = "\n\n".join(page_texts).strip()
            first_page_text = page_texts[0] if page_texts else ""
            return full_text, first_page_text
        except Exception as exc:
            log_event(logger, "ncert_pdf_extract_failed", path=str(pdf_path), error=str(exc))
            return "", ""

    def _looks_like_supplementary(self, pdf_path: Path, first_page_text: str) -> bool:
        stem = pdf_path.stem.casefold()
        if stem.endswith("ps") or stem.endswith("an"):
            return True

        preview = " ".join(first_page_text.split()).casefold()
        markers = [
            "prelims",
            "appendix",
            "appendices",
            "answers to exercises",
            "answer key",
            "index",
        ]
        return any(marker in preview for marker in markers)

    def _infer_pdf_labels(self, first_page_text: str, pdf_path: Path) -> tuple[str | None, str | None, str | None]:
        lines = [self._clean_line(line) for line in first_page_text.splitlines()]
        lines = [line for line in lines if line]

        chapter: str | None = None
        unit_name: str | None = None

        for line in lines[:20]:
            if re.search(r"\bUnit\s+\d+\b", line, re.IGNORECASE):
                unit_name = line
                break

        for line in lines[:10]:
            if re.fullmatch(r"CHAPTER\s+[A-Z0-9-]+", line.strip(), re.IGNORECASE):
                chapter = line.title()
                break
            if re.fullmatch(r"Chapter\s+\d+.*", line.strip(), re.IGNORECASE):
                chapter = line.strip()
                break

        topic_name = self._infer_topic_name(lines)
        if not chapter:
            chapter = unit_name or pdf_path.stem

        return chapter, unit_name, topic_name or pdf_path.stem

    def _infer_topic_name(self, lines: list[str]) -> str | None:
        fallback: str | None = None

        for line in lines[:20]:
            candidate = re.sub(r"^\d+[\.\)]?\s*", "", line).strip()
            if not candidate:
                continue

            upper = candidate.upper()
            lower = candidate.casefold()

            if ".indd" in lower:
                continue
            if "reprint" in lower:
                continue
            if "grade " in lower and len(candidate.split()) <= 4:
                continue
            if upper.startswith("CHAPTER "):
                continue
            if upper.startswith("APPENDIX"):
                continue
            if lower in {"contents", "textbook", "physics", "santoor"}:
                continue

            if lower.startswith("let us "):
                if fallback is None:
                    fallback = candidate
                continue

            if len(candidate.split()) > 18:
                continue

            return candidate

        return fallback

    def _build_topic_summary(self, full_text: str, topic_name: str | None) -> str:
        text = full_text.strip()
        if not text:
            return ""

        if topic_name:
            idx = text.casefold().find(topic_name.casefold())
            if idx != -1:
                text = text[idx + len(topic_name):].strip()

        text = re.sub(r"\s+", " ", text).strip()
        return text[:700]

    def _build_lesson_goal(self, subject: str, topic_name: str | None, book: str) -> str:
        topic_label = topic_name or "this chapter"
        subject_lower = subject.strip().casefold()

        if subject_lower == "english":
            return (
                f"Help students understand '{topic_label}' from the NCERT book '{book}', "
                f"with focus on reading comprehension, vocabulary, discussion, and classroom participation."
            )

        if subject_lower == "physics":
            return (
                f"Help students understand the core concepts in '{topic_label}' from the NCERT book '{book}', "
                f"with focus on definitions, explanation, examples, and problem-solving readiness."
            )

        return (
            f"Teach the key ideas of '{topic_label}' from the NCERT book '{book}' "
            f"in a classroom-ready way for {subject}."
        )

    def _normalize_grade(self, value: str) -> str:
        cleaned = value.strip()
        match = re.search(r"(\d+)", cleaned)
        return match.group(1) if match else cleaned

    def _clean_line(self, value: str) -> str:
        value = re.sub(r"\s+", " ", value or "").strip()
        return value

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

    def _normalize_records(self, records: list[dict]) -> tuple[list[NcertContent], int]:
        rows: list[NcertContent] = []
        skipped_non_english = 0

        for record in records:
            grade = self._clean(record.get("grade"))
            subject = self._clean(record.get("subject"))

            chapter = self._clean(record.get("chapter")) or None
            topic = self._clean(record.get("topic")) or None
            source_title = self._clean(record.get("source_title") or record.get("source_reference"))
            content = self._clean(record.get("content_chunk") or record.get("content") or record.get("topic_summary"))

            book = self._clean(record.get("book")) or None
            book_url = self._clean(record.get("book_url")) or None
            unit_name = self._clean(record.get("unit_name") or chapter) or None
            topic_name = self._clean(record.get("topic_name") or topic) or None
            topic_summary = self._clean(record.get("topic_summary") or content) or None
            lesson_goal = self._clean(record.get("lesson_goal")) or None
            source_reference = self._clean(record.get("source_reference") or source_title) or None

            keywords = self._keywords_string(
                record,
                grade,
                subject,
                chapter,
                topic,
                book,
                book_url,
                unit_name,
                topic_name,
                source_title,
                source_reference,
                topic_summary,
                lesson_goal,
                content,
            )

            if not grade or not subject or not source_title or not content:
                raise ValueError(
                    "Each NCERT record must include grade, subject, source_title/source_reference, and content/content_chunk/topic_summary."
                )

            for chunk in self._chunk_text(content):
                if not self._is_probably_english_text(chunk):
                    skipped_non_english += 1
                    continue

                rows.append(
                    NcertContent(
                        grade=grade,
                        subject=subject,
                        chapter=chapter,
                        topic=topic,
                        source_title=source_title,
                        content_chunk=chunk,
                        book=book,
                        book_url=book_url,
                        unit_name=unit_name,
                        topic_name=topic_name,
                        topic_summary=topic_summary,
                        lesson_goal=lesson_goal,
                        source_reference=source_reference,
                        keywords=keywords,
                    )
                )

        return rows, skipped_non_english

    def _clean(self, value: object) -> str:
        return str(value or "").strip()

    def _keywords_string(
        self,
        record: dict,
        grade: str,
        subject: str,
        chapter: str | None,
        topic: str | None,
        book: str | None,
        book_url: str | None,
        unit_name: str | None,
        topic_name: str | None,
        source_title: str,
        source_reference: str | None,
        topic_summary: str | None,
        lesson_goal: str | None,
        content: str,
    ) -> str:
        explicit = self._clean(record.get("keywords"))
        tokens: list[str] = []

        if explicit:
            tokens.extend(re.split(r"[,;|]", explicit))

        tokens.extend(
            [
                grade,
                subject,
                chapter or "",
                topic or "",
                book or "",
                book_url or "",
                unit_name or "",
                topic_name or "",
                source_title,
                source_reference or "",
            ]
        )

        tokens.extend(re.findall(r"[A-Za-z][A-Za-z0-9-]+", topic_summary or "")[:15])
        tokens.extend(re.findall(r"[A-Za-z][A-Za-z0-9-]+", lesson_goal or "")[:15])
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

    def _derive_processing_context(
        self,
        records: list[dict],
        file_path: Path | None = None,
    ) -> tuple[str | None, str | None, str | None]:
        grade: str | None = None
        subject: str | None = None
        book: str | None = None

        for record in records:
            if not grade:
                value = self._clean(record.get("grade"))
                grade = value or None

            if not subject:
                value = self._clean(record.get("subject"))
                subject = value or None

            if not book:
                value = self._clean(record.get("book"))
                if not value:
                    value = self._clean(record.get("source_title"))
                book = value or None

            if grade and subject and book:
                break

        if not book and file_path is not None:
            book = file_path.stem

        return grade, subject, book

    def _is_probably_english_text(self, text: str) -> bool:
        if not text or not text.strip():
            return False

        total_alpha = 0
        non_latin_alpha = 0

        for ch in text:
            if not ch.isalpha():
                continue

            total_alpha += 1
            char_name = unicodedata.name(ch, "")
            if "LATIN" not in char_name:
                non_latin_alpha += 1

        if total_alpha == 0:
            return False

        return non_latin_alpha == 0