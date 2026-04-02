import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.services.ncert_ingestion_service import NcertIngestionService


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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target = args.file or args.dir
    if not target:
        print("Please provide --file or --dir")
        return 1

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        summary = NcertIngestionService(db).ingest_path(
            target,
            truncate_first=args.truncate_first,
            include_supplementary=args.include_supplementary,
        )
        print(
            f"NCERT ingest complete: files={summary.files_processed}, "
            f"records={summary.records_processed}, chunks={summary.chunks_created}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())