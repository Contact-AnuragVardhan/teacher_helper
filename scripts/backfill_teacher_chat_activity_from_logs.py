"""Backfill teacher_chat_activity from retained application/hosting logs.

The production app historically logged one `conversation_inbound` event per handled
message, including the teacher WhatsApp number. This utility converts those retained
log events into timestamp-only teacher_chat_activity rows so ADMIN usage reports can
cover days before the new table was deployed.

The log line must contain an ISO-8601/RFC3339 timestamp (for example a Render log
prefix or a JSON `timestamp` field) and the `conversation_inbound` JSON event.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.teacher_chat_activity import TeacherChatActivity
from app.repositories.teacher_repository import TeacherRepository

ISO_TS_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2}))"
)


def _canonical_phone(value: str) -> str:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    return f"+{digits}" if digits else ""


def _parse_timestamp(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    # Normalize offsets such as +0530 to +05:30.
    if re.search(r"[+-]\d{4}$", raw):
        raw = raw[:-5] + raw[-5:-2] + ":" + raw[-2:]
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _json_objects_from_line(line: str):
    # Hosting exports may wrap the application JSON in another JSON object.
    try:
        outer = json.loads(line)
    except Exception:
        outer = None
    if isinstance(outer, dict):
        yield outer
        for key in ("message", "msg", "log", "text"):
            nested = outer.get(key)
            if isinstance(nested, str):
                try:
                    parsed = json.loads(nested)
                except Exception:
                    continue
                if isinstance(parsed, dict):
                    yield parsed

    # Also scan for the app JSON object in prefixed plain-text lines.
    start = line.find("{")
    if start >= 0:
        try:
            parsed = json.loads(line[start:])
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            yield parsed


def parse_conversation_inbound(line: str) -> tuple[datetime, str] | None:
    timestamp: datetime | None = None
    phone = ""

    objects = list(_json_objects_from_line(line))
    for obj in objects:
        if timestamp is None:
            for key in ("timestamp", "ts", "time", "datetime", "@timestamp"):
                if key in obj:
                    timestamp = _parse_timestamp(str(obj.get(key) or ""))
                    if timestamp:
                        break

        event = str(obj.get("event") or "")
        message = str(obj.get("message") or "")
        if event == "conversation_inbound" or message == "conversation_inbound":
            phone = _canonical_phone(str(obj.get("whatsapp_number") or ""))

    if timestamp is None:
        match = ISO_TS_RE.search(line)
        if match:
            timestamp = _parse_timestamp(match.group("ts"))

    if timestamp and phone:
        return timestamp, phone
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-file", required=True, help="Exported Render/application log file")
    parser.add_argument("--from-date", dest="from_date", help="Local report date YYYY-MM-DD")
    parser.add_argument("--to-date", dest="to_date", help="Local report date YYYY-MM-DD, inclusive")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = get_settings()

    start_date = date.fromisoformat(args.from_date) if args.from_date else None
    end_date = date.fromisoformat(args.to_date) if args.to_date else None
    zone = ZoneInfo(settings.admin_report_timezone)

    db = SessionLocal()
    try:
        teacher_repo = TeacherRepository(db)
        teacher_by_phone: dict[str, object | None] = {}
        inserted = 0
        skipped = 0
        missing_profile = 0
        seen: set[tuple[int, datetime]] = set()

        log_text = Path(args.log_file).read_text(encoding="utf-8-sig", errors="replace")

        # Render CLI `--output json` emits pretty-printed JSON objects one after
        # another (not NDJSON), so parse the whole stream first. Fall back to
        # line-oriented parsing for ordinary application logs.
        records: list[str] = []
        decoder = json.JSONDecoder()
        pos = 0
        parsed_stream = False
        while pos < len(log_text):
            while pos < len(log_text) and log_text[pos].isspace():
                pos += 1
            if pos >= len(log_text):
                break
            try:
                obj, end = decoder.raw_decode(log_text, pos)
            except json.JSONDecodeError:
                records = log_text.splitlines()
                break
            if isinstance(obj, dict):
                records.append(json.dumps(obj, ensure_ascii=False))
                parsed_stream = True
            pos = end

        if not parsed_stream and not records:
            records = log_text.splitlines()

        for record in records:
            parsed = parse_conversation_inbound(record)
            if not parsed:
                continue
            occurred_at, phone = parsed

            # Backfill ALL Teacher Helper activity. ADMIN_TEACHERS is intentionally
            # NOT used here; that env variable only controls which teachers ADMIN
            # may select/view.
            if phone not in teacher_by_phone:
                teacher_by_phone[phone] = teacher_repo.get_by_whatsapp_number(phone)
            teacher = teacher_by_phone[phone]
            if teacher is None:
                # The current table requires teacher_id, so an inbound number with
                # no teacher_profile cannot be inserted safely.
                missing_profile += 1
                continue

            local_date = occurred_at.replace(tzinfo=timezone.utc).astimezone(zone).date()
            if start_date and local_date < start_date:
                continue
            if end_date and local_date > end_date:
                continue

            key = (teacher.id, occurred_at)
            if key in seen:
                skipped += 1
                continue
            seen.add(key)

            exists = (
                db.query(TeacherChatActivity.id)
                .filter(
                    TeacherChatActivity.teacher_id == teacher.id,
                    TeacherChatActivity.occurred_at == occurred_at,
                )
                .first()
            )
            if exists:
                skipped += 1
                continue

            db.add(
                TeacherChatActivity(
                    teacher_id=teacher.id,
                    whatsapp_number=teacher.whatsapp_number,
                    occurred_at=occurred_at,
                )
            )
            inserted += 1

        if args.dry_run:
            db.rollback()
        else:
            db.commit()

        mode = "would insert" if args.dry_run else "inserted"
        print(
            f"{mode}: {inserted}; duplicates skipped: {skipped}; "
            f"missing teacher_profile: {missing_profile}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
