import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.services.ncert_ingestion_service import IngestionSummary, NcertIngestionService

logger = logging.getLogger(__name__)


subject_book_dict: Dict[int, Dict[str, List[str]]] = {
    1: {
        "English": ["Mridang"],
        "Mathematics": ["Joyful-Mathematics (English)"],
    },
    2: {
        "Mathematics": ["Joyful-Mathematics (English)"],
        "English": ["Mridang"]
    },
    3: {
        "Mathematics": ["Maths Mela"],
        "English": ["Santoor"],
        "The World Around Us": ["Our Wondrous World"],
        "Arts": ["Bansuri - I"],
        "Physical Education and Well Being": ["Khel Yoga"],
    },
    4: {
        "Mathematics": ["Math-Mela"],
        "English": ["Santoor"],
        "The World Around Us": ["Our Wonderous World"],
        "Arts": ["Bansuri"],
        "Physical Education and Well Being": ["Khel Yoga"],
    },
    5: {
        "Mathematics": ["Math-Mela"],
        "English": ["Santoor"],
        "The World Around Us": ["Our Wonderous World"],
        "Arts": ["Bansuri"],
        "Physical Education and Well Being": ["Khel Yoga"],
    },
    6: {
        "English": ["Poorvi"],
        "Mathematics": ["Ganita Prakash"],
        "Social Science": ["Exploring Society India and Beyond"],
        "Science": ["Curiosity"],
        "Arts": ["Kriti-I"],
        "Physical Education and Well Being": ["Khel Yatra"],
        "Vocational Education": ["Kaushal Bodh"],
    },
    7: {
        "English": ["Poorvi"],
        "Mathematics": ["Ganita Prakash", "Ganita Prakash-II"],
        "Social Science": [
            "Exploring Society India and Beyond Part-I",
            "Exploring Society India and Beyond Part-II",
        ],
        "Science": ["Curiosity"],
        "Arts": ["Kriti"],
        "Physical Education and Well Being": ["Khel Yatra"],
        "Vocational Education": ["Kaushal Bodh"],
    },
    8: {
        "English": ["Poorvi"],
        "Mathematics": ["Ganita Prakash Part-I", "Ganita Prakash Part-II"],
        "Social Science": ["Exploring Society India and Beyond Part-I"],
        "Science": ["Curiosity"],
        "Arts": ["Kriti"],
        "Physical Education and Well Being": ["Khel Yatra"],
        "Vocational Education": ["Kaushal Bodh"],
    },
    9: {
        "English": ["Beehive", "Moments Supplementary Reader", "Words and Expressions  1"],
        "Mathematics": ["Mathematics"],
        "Science": ["Science"],
        "Social Science": [
            "Democratic Politics-I",
            "Contemporary India-I",
            "Economics",
            "India and the Contemporary World-I",
        ],
        "Health and Physical Education": ["Health and Physical Education"],
        "ICT": ["Information and Communication Technology"],
    },
    10: {
        "Mathematics": ["Mathematics"],
        "Science": ["Science"],
        "Social Science": [
            "Contemporary India ",
            "Understanding Economic Development",
            "India and the Contemporary World-II ",
            "Democratic Politics",
        ],
        "English": ["First Flight", "Foot Prints Without feet Supp. Reader", "Words and Expressions  2"],
        "Health and Physical Education": ["Health and Physical Education"],
    },
    11: {
        "Accountancy": ["Financial Accounting-I", "Accountancy-II"],
        "Chemistry": ["Chemistry Part-I", "Chemistry Part II"],
        "Mathematics": ["Mathematics"],
        "Biology": ["Biology"],
        "Psychology": ["Introduction to Psychology"],
        "Geography": ["Fundamental of Physical Geography", "India Physical Environment"],
        "Physics": ["Physics Part-I", "Physics Part-II"],
        "Sociology": ["Introducing Sociology", "Understanding Society"],
        "English": ["Woven Words", "Hornbill", "Snapshots Suppl.Reader English"],
        "Political Science": ["Political Theory", "India Constitution at Work"],
        "History": ["Themes in World History"],
        "Economics": ["Indian Economic Development", "Statistics for Economics"],
        "Business Studies": ["Business Studies"],
        "Home Science": ["Human Ecology and Family Sciences Part I ", "Human Ecology and Family Sciences Part II "],
        "Creative Writing and Translation": ["Srijan", "Takhleequi Jauhar"],
        "Fine Art": ["An Introduction to Indian Art Part-I"],
        "Informatics Practices": ["Informatics Practices"],
        "Computer Science": ["Computer Science"],
        "Health and Physical Education": ["Health and Physical Education"],
        "Biotechnology": ["Biotechnology"],
        "Knowledge Traditions Practices of India": ["Knowledge Traditions Practices of India"],
    },
    12: {
        "Mathematics": ["Mathematics Part-I", "Mathematics Part-II"],
        "Physics": ["Physics Part-I", "Physics Part-II"],
        "Accountancy": ["Accountancy-I", "Accountancy Part-II"],
        "English": ["Kaliedoscope", "Flamingo", "Vistas"],
        "Biology": ["Biology"],
        "History": ["Themes in Indian History-I", "Themes in Indian History-II", "Themes in Indian History-III"],
        "Geography": ["Fundamentals of Human Geography", "Practical Work in Geography Part II", "India -People And Economy"],
        "Psychology": ["Psychology"],
        "Sociology": ["Indian Society", "Bhartiya Samaj", "Social Change and Development in India"],
        "Chemistry": ["Chemistry-I", "Chemistry-II"],
        "Political Science": ["Contemporary World Politics", "Politics in India Since Independence"],
        "Economics": ["Introductory Microeconomics", "Introductory Macroeconomics"],
        "Business Studies": ["Business Studies-I", "Business Studies-II"],
        "Home Science": ["Human Ecology and Family Sciences Part I ", "Human Ecology and Family Sciences Part II "],
        "Creative Writing & Translation": ["Srijan-II"],
        "Fine Art": ["An Introduction to Indian Art Part-II"],
        "Computer Science": ["Computer Science"],
        "Informatics Practices": ["Informatics Practices"],
        "Biotechnology": ["Biotechnology"],
    },
}


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest NCERT content from JSON/CSV files or from a Grade/Subject/Book folder structure containing PDFs."
    )
    parser.add_argument("--file", help="Path to one JSON or CSV file.")
    parser.add_argument("--dir", help="Path to a directory containing JSON/CSV files or NCERT book folders.")
    parser.add_argument(
        "--truncate-first",
        action="store_true",
        help="Delete existing NCERT content before ingesting.",
    )
    parser.add_argument(
        "--include-supplementary",
        action="store_true",
        help="Include prelims, appendices, and answer-section PDFs. By default these are skipped.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level.",
    )
    return parser.parse_args()


def _normalize_text(value: str | None) -> str:
    cleaned = str(value or "").strip().casefold()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _normalize_grade_key(value: str | int | None) -> str:
    cleaned = str(value or "").strip()
    match = re.search(r"(\d+)", cleaned)
    return match.group(1) if match else cleaned


def _build_allowed_mapping() -> dict[str, dict[str, set[str]]]:
    allowed: dict[str, dict[str, set[str]]] = {}
    for grade, subject_map in subject_book_dict.items():
        normalized_grade = _normalize_grade_key(grade)
        allowed[normalized_grade] = {}
        for subject, books in subject_map.items():
            allowed[normalized_grade][_normalize_text(subject)] = {_normalize_text(book) for book in books}
    return allowed


ALLOWED_MAPPING = _build_allowed_mapping()


def _is_allowed_grade_subject_book(grade: str | None, subject: str | None, book: str | None) -> bool:
    normalized_grade = _normalize_grade_key(grade)
    normalized_subject = _normalize_text(subject)
    normalized_book = _normalize_text(book)

    subject_map = ALLOWED_MAPPING.get(normalized_grade)
    if not subject_map:
        return False

    allowed_books = subject_map.get(normalized_subject)
    if allowed_books is None:
        return False

    if not normalized_book:
        return True

    return normalized_book in allowed_books


def _should_skip_existing_combo(
    service: NcertIngestionService,
    grade: str,
    subject: str,
    approved_combinations: set[tuple[str, str]],
    skipped_existing_combinations: set[tuple[str, str]],
) -> bool:
    combo = (_normalize_grade_key(grade), _normalize_text(subject))

    if combo in approved_combinations:
        return False

    if combo in skipped_existing_combinations:
        return True

    if service.repo.exists_for_grade_and_subject(grade, subject):
        skipped_existing_combinations.add(combo)
        logger.info(
            "SKIP COMBO | grade=%s | subject=%s | reason=already_exists_in_db",
            grade,
            subject,
        )
        return True

    approved_combinations.add(combo)
    return False


def _zero_summary() -> IngestionSummary:
    return IngestionSummary(files_processed=0, records_processed=0, chunks_created=0)


def _add_summary(total: IngestionSummary, current: IngestionSummary) -> IngestionSummary:
    return IngestionSummary(
        files_processed=total.files_processed + current.files_processed,
        records_processed=total.records_processed + current.records_processed,
        chunks_created=total.chunks_created + current.chunks_created,
    )


def _process_single_file(
    service: NcertIngestionService,
    file_path: Path,
    include_supplementary: bool,
    approved_combinations: set[tuple[str, str]],
    skipped_existing_combinations: set[tuple[str, str]],
) -> IngestionSummary:
    raw_records = service._read_records(file_path)
    grade, subject, book = service._derive_processing_context(raw_records, file_path)
    has_explicit_book = any(service._clean(record.get("book")) for record in raw_records)
    allowed_book = book if has_explicit_book else None

    if not grade or not subject:
        logger.warning("SKIP FILE | file=%s | reason=missing_grade_or_subject", file_path)
        return _zero_summary()

    if not _is_allowed_grade_subject_book(grade, subject, allowed_book):
        logger.info(
            "SKIP FILE | file=%s | grade=%s | subject=%s | book=%s | reason=not_in_subject_book_dict",
            file_path,
            grade,
            subject,
            book or "-",
        )
        return _zero_summary()

    if _should_skip_existing_combo(service, grade, subject, approved_combinations, skipped_existing_combinations):
        return _zero_summary()

    return service.ingest_path(
        file_path,
        truncate_first=False,
        include_supplementary=include_supplementary,
    )


def _process_directory(
    service: NcertIngestionService,
    directory: Path,
    include_supplementary: bool,
) -> IngestionSummary:
    total = _zero_summary()
    approved_combinations: set[tuple[str, str]] = set()
    skipped_existing_combinations: set[tuple[str, str]] = set()

    structured_files = sorted(
        path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in {".json", ".csv"}
    )
    book_dirs = sorted({url_file.parent for url_file in directory.rglob("url.txt")})

    logger.info(
        "FILTERED NCERT INGEST STARTED | path=%s | structured_files=%s | book_dirs=%s",
        directory,
        len(structured_files),
        len(book_dirs),
    )

    for file_path in structured_files:
        total = _add_summary(
            total,
            _process_single_file(
                service,
                file_path,
                include_supplementary,
                approved_combinations,
                skipped_existing_combinations,
            ),
        )

    for book_dir in book_dirs:
        rel_parts = book_dir.relative_to(directory).parts
        if len(rel_parts) < 3:
            logger.warning("SKIP BOOK DIR | path=%s | reason=unexpected_folder_structure", book_dir)
            continue

        grade = _normalize_grade_key(rel_parts[0])
        subject = rel_parts[1].strip()
        book = book_dir.name.strip()

        if not _is_allowed_grade_subject_book(grade, subject, book):
            logger.info(
                "SKIP BOOK | path=%s | grade=%s | subject=%s | book=%s | reason=not_in_subject_book_dict",
                book_dir,
                grade,
                subject,
                book,
            )
            continue

        if _should_skip_existing_combo(service, grade, subject, approved_combinations, skipped_existing_combinations):
            continue

        total = _add_summary(
            total,
            service.ingest_book_directory(
                root_path=directory,
                book_dir=book_dir,
                include_supplementary=include_supplementary,
            ),
        )

    return total


def main() -> int:
    args = parse_args()
    configure_logging(args.log_level)

    target = args.file or args.dir
    if not target:
        print("Please provide --file or --dir")
        return 1

    logger.info(
        "NCERT ingest started | target=%s | truncate_first=%s | include_supplementary=%s",
        target,
        args.truncate_first,
        args.include_supplementary,
    )

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        service = NcertIngestionService(db)

        if args.truncate_first:
            service.repo.truncate()
            logger.info("TRUNCATED existing NCERT content | target=%s", target)

        input_path = Path(target)
        if not input_path.exists():
            print(f"Path not found: {input_path}")
            return 1

        if input_path.is_file():
            summary = _process_single_file(
                service,
                input_path,
                args.include_supplementary,
                approved_combinations=set(),
                skipped_existing_combinations=set(),
            )
        else:
            summary = _process_directory(
                service,
                input_path,
                args.include_supplementary,
            )

        logger.info(
            "NCERT ingest complete | files=%s | records=%s | chunks=%s",
            summary.files_processed,
            summary.records_processed,
            summary.chunks_created,
        )

        print(
            f"NCERT ingest complete: files={summary.files_processed}, "
            f"records={summary.records_processed}, chunks={summary.chunks_created}"
        )
        return 0
    except Exception:
        logger.exception("NCERT ingest failed")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())