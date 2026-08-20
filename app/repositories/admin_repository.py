from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.core.logging import get_logger, log_event
from app.models.teacher_chat_activity import TeacherChatActivity

logger = get_logger(__name__)


class AdminRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def report_zone(timezone_name: str) -> ZoneInfo:
        try:
            return ZoneInfo((timezone_name or "").strip() or "UTC")
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    def record_teacher_activity(
        self,
        *,
        teacher,
        whatsapp_number: str,
        occurred_at: datetime | None = None,
    ) -> TeacherChatActivity:
        activity = TeacherChatActivity(
            teacher_id=teacher.id,
            whatsapp_number=whatsapp_number,
            occurred_at=occurred_at or datetime.utcnow(),
        )
        self.db.add(activity)
        self.db.commit()
        self.db.refresh(activity)
        log_event(
            logger,
            "teacher_chat_activity_recorded",
            teacher_id=teacher.id,
            whatsapp_number=whatsapp_number,
            activity_id=activity.id,
        )
        return activity

    def _utc_bounds_for_local_dates(
        self,
        *,
        start_date: date,
        end_date_exclusive: date,
        timezone_name: str,
    ) -> tuple[datetime, datetime, ZoneInfo]:
        zone = self.report_zone(timezone_name)
        local_start = datetime.combine(start_date, time.min, tzinfo=zone)
        local_end = datetime.combine(end_date_exclusive, time.min, tzinfo=zone)
        start_utc = local_start.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = local_end.astimezone(timezone.utc).replace(tzinfo=None)
        return start_utc, end_utc, zone

    def utc_bounds_for_week(
        self,
        *,
        week_start: date,
        timezone_name: str,
    ) -> tuple[datetime, datetime]:
        start_utc, end_utc, _ = self._utc_bounds_for_local_dates(
            start_date=week_start,
            end_date_exclusive=week_start + timedelta(days=7),
            timezone_name=timezone_name,
        )
        return start_utc, end_utc


    def first_activity_at(self) -> datetime | None:
        """Earliest timestamp currently represented in the usage audit table."""
        row = (
            self.db.query(TeacherChatActivity.occurred_at)
            .order_by(TeacherChatActivity.occurred_at.asc())
            .first()
        )
        return row[0] if row else None

    def daily_usage_minutes(
        self,
        *,
        teacher_id: int,
        week_start: date,
        timezone_name: str,
        session_timeout_minutes: int,
    ) -> dict[date, int]:
        week_end_exclusive = week_start + timedelta(days=7)
        start_utc, end_utc, zone = self._utc_bounds_for_local_dates(
            start_date=week_start,
            end_date_exclusive=week_end_exclusive,
            timezone_name=timezone_name,
        )
        rows = (
            self.db.query(TeacherChatActivity)
            .filter(
                TeacherChatActivity.teacher_id == teacher_id,
                TeacherChatActivity.occurred_at >= start_utc,
                TeacherChatActivity.occurred_at < end_utc,
            )
            .order_by(TeacherChatActivity.occurred_at.asc())
            .all()
        )

        grouped: dict[date, list[datetime]] = defaultdict(list)
        for row in rows:
            utc_aware = row.occurred_at.replace(tzinfo=timezone.utc)
            local_dt = utc_aware.astimezone(zone)
            grouped[local_dt.date()].append(local_dt)

        timeout = timedelta(minutes=max(1, session_timeout_minutes))
        result: dict[date, int] = {}
        for offset in range(7):
            current_date = week_start + timedelta(days=offset)
            events = grouped.get(current_date, [])
            if not events:
                result[current_date] = 0
                continue

            # Treat a gap longer than the normal TH session timeout as a new chat session.
            # Each distinct session gets a 1-minute minimum so a single-message interaction
            # is visible in the report instead of looking like zero use.
            total_seconds = 0.0
            session_start = events[0]
            session_last = events[0]
            for event in events[1:]:
                if event - session_last > timeout:
                    total_seconds += max(60.0, (session_last - session_start).total_seconds())
                    session_start = event
                session_last = event
            total_seconds += max(60.0, (session_last - session_start).total_seconds())
            result[current_date] = int(math.ceil(total_seconds / 60.0))

        return result
