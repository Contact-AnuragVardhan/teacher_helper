from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import logging
import re
import unicodedata
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.core.config import Settings
from app.core.language import language_key, normalize_language


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LessonPdfMetadata:
    teacher_name: str = ""
    school_name: str = ""
    grade: str = ""
    subject: str = ""
    duration_minutes: int | None = None
    book_title: str = ""
    chapter_title: str = ""
    section_title: str = ""
    day_title: str = ""
    pages: str = ""
    is_customized: bool = False
    preferred_language: str = "English"


@dataclass(frozen=True)
class GeneratedLessonPdf:
    filename: str
    content: bytes


class LessonPdfService:
    """Build a printable PDF for the currently generated lesson plan."""

    _DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
    _BULLET_RE = re.compile(r"^\s*(?:[-*•▪◦]|\d+[.)])\s+(.*)$")
    _MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
    _WHATSAPP_BOLD_LINE_RE = re.compile(r"^\*(?!\s)(.+?)\*$")

    def __init__(self, settings: Settings):
        self.settings = settings

    def generate(
        self,
        *,
        lesson_text: str,
        metadata: LessonPdfMetadata,
    ) -> GeneratedLessonPdf:
        normalized_lesson = self._normalize_text(lesson_text)
        if not normalized_lesson:
            raise ValueError("Generated lesson text is empty.")

        labels = self._labels_for_language(metadata.preferred_language)
        font_probe = "\n".join(
            [
                normalized_lesson,
                metadata.teacher_name,
                metadata.school_name,
                metadata.subject,
                metadata.book_title,
                metadata.chapter_title,
                metadata.section_title,
                metadata.day_title,
                *labels.values(),
            ]
        )
        font_name, bold_font_name, shaping = self._register_fonts(font_probe)
        styles = self._build_styles(font_name, bold_font_name, shaping)

        buffer = BytesIO()
        document = BaseDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=17 * mm,
            leftMargin=17 * mm,
            topMargin=18 * mm,
            bottomMargin=18 * mm,
            title=f"Teacher Helper - {labels['title']}",
            author="Teacher Helper",
            subject=labels["document_subject"],
        )

        frame = Frame(
            document.leftMargin,
            document.bottomMargin,
            document.width,
            document.height,
            id="lesson-frame",
        )
        document.addPageTemplates(
            [
                PageTemplate(
                    id="lesson-template",
                    frames=[frame],
                    onPage=lambda canvas, doc: self._draw_page_decorations(
                        canvas,
                        doc,
                        font_name=font_name,
                        bold_font_name=bold_font_name,
                        page_label=labels["page"],
                    ),
                )
            ]
        )

        story = [
            Paragraph("Teacher Helper", styles["brand"]),
            Paragraph(labels["title"], styles["title"]),
            Spacer(1, 3 * mm),
            self._metadata_table(metadata, styles, labels),
            Spacer(1, 5 * mm),
        ]
        story.extend(self._lesson_flowables(normalized_lesson, styles))

        document.build(story)
        pdf_bytes = buffer.getvalue()
        if not pdf_bytes.startswith(b"%PDF"):
            raise RuntimeError("PDF generation did not produce a valid PDF document.")

        return GeneratedLessonPdf(
            filename=self._build_filename(metadata),
            content=pdf_bytes,
        )

    @staticmethod
    def _labels_for_language(preferred_language: str) -> dict[str, str]:
        key = language_key(normalize_language(preferred_language) or "English")
        if key == "hindi":
            return {
                "title": "विस्तृत पाठ योजना",
                "document_subject": "तैयार की गई पाठ योजना",
                "teacher": "शिक्षक",
                "school": "विद्यालय",
                "grade": "ग्रेड / कक्षा",
                "subject": "विषय",
                "duration": "अवधि",
                "minutes": "मिनट",
                "book": "पुस्तक",
                "chapter": "अध्याय",
                "section": "खंड",
                "day": "दिन",
                "book_pages": "पुस्तक पृष्ठ",
                "lesson_type": "पाठ प्रकार",
                "customized": "अनुकूलित",
                "generated": "तैयार किया गया",
                "page": "पृष्ठ",
            }
        # Hinglish uses Roman script and keeps concise structural labels in English.
        return {
            "title": "Detailed Lesson Plan",
            "document_subject": "Generated lesson plan",
            "teacher": "Teacher",
            "school": "School",
            "grade": "Grade / Class",
            "subject": "Subject",
            "duration": "Duration",
            "minutes": "minutes",
            "book": "Book",
            "chapter": "Chapter",
            "section": "Section",
            "day": "Day",
            "book_pages": "Book Pages",
            "lesson_type": "Lesson Type",
            "customized": "Customized",
            "generated": "Generated",
            "page": "Page",
        }

    def _register_fonts(self, text: str) -> tuple[str, str, bool]:
        """Register the best available font without making PDF generation fail.

        For lessons containing Devanagari, prefer a mixed-script Unicode font
        (FreeSans) so a single paragraph can safely contain Hindi, English and
        common mathematical symbols such as ², ≠, ≤, ≥ and √.
        """
        uses_devanagari = bool(self._DEVANAGARI_RE.search(text))
        project_font_dir = Path(__file__).resolve().parents[2] / "assets" / "fonts"

        if uses_devanagari:
            regular_candidates = [
                self.settings.lesson_pdf_devanagari_font_path,
                str(project_font_dir / "FreeSans.ttf"),
                self.settings.lesson_pdf_font_path,
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
                "/usr/local/share/fonts/FreeSans.ttf",
                # Keep Devanagari-specific fonts only as later fallbacks. A bundled
                # FreeSans is preferred because lesson text is usually mixed-script.
                "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
                "/usr/local/share/fonts/NotoSansDevanagari-Regular.ttf",
            ]
            bold_candidates = [
                self.settings.lesson_pdf_devanagari_bold_font_path,
                str(project_font_dir / "FreeSansBold.ttf"),
                self.settings.lesson_pdf_bold_font_path,
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
                "/usr/local/share/fonts/FreeSansBold.ttf",
                "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
                "/usr/local/share/fonts/NotoSansDevanagari-Bold.ttf",
            ]
            prefix = "TeacherHelperUnicode"
        else:
            regular_candidates = [
                self.settings.lesson_pdf_font_path,
                str(project_font_dir / "FreeSans.ttf"),
                "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
                "/usr/local/share/fonts/NotoSans-Regular.ttf",
                "/usr/local/share/fonts/FreeSans.ttf",
            ]
            bold_candidates = [
                self.settings.lesson_pdf_bold_font_path,
                str(project_font_dir / "FreeSansBold.ttf"),
                "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
                "/usr/local/share/fonts/NotoSans-Bold.ttf",
                "/usr/local/share/fonts/FreeSansBold.ttf",
            ]
            prefix = "TeacherHelperSans"

        regular_path = self._first_existing_path(regular_candidates)
        bold_path = self._first_existing_path(bold_candidates)

        if regular_path:
            regular_name = f"{prefix}-Regular"
            bold_name = f"{prefix}-Bold"

            if regular_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(regular_name, regular_path))

            if bold_path:
                if bold_name not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(bold_name, bold_path))
            else:
                # A missing bold font must never prevent PDF generation.
                bold_name = regular_name

            # Shaping is desirable for Devanagari. If uharfbuzz is unexpectedly
            # unavailable, continue rather than failing the Print Lesson flow.
            shaping = uses_devanagari and self._harfbuzz_available()
            if uses_devanagari and not shaping:
                logger.warning(
                    "Devanagari text detected but uharfbuzz is unavailable; "
                    "PDF generation will continue without shaping."
                )

            return regular_name, bold_name, shaping

        # Final non-failing fallback. With assets/fonts/FreeSans.ttf committed,
        # production should not normally reach this branch for Hindi content.
        if uses_devanagari:
            logger.warning(
                "Devanagari text detected but no configured/bundled Unicode font "
                "was found. Falling back to Helvetica; Hindi glyphs may not render."
            )
        return "Helvetica", "Helvetica-Bold", False

    @staticmethod
    def _first_existing_path(candidates: list[str | None]) -> str | None:
        for candidate in candidates:
            value = (candidate or "").strip()
            if value and Path(value).is_file():
                return value
        return None

    @staticmethod
    def _harfbuzz_available() -> bool:
        try:
            import uharfbuzz  # noqa: F401
        except ImportError:
            return False
        return True

    @staticmethod
    def _build_styles(font_name: str, bold_font_name: str, shaping: bool) -> dict[str, ParagraphStyle]:
        sample = getSampleStyleSheet()
        base = dict(fontName=font_name, leading=15, textColor=colors.HexColor("#1F2937"))
        shaping_value = 1 if shaping else 0
        return {
            "brand": ParagraphStyle(
                "LessonBrand",
                parent=sample["Normal"],
                fontName=bold_font_name,
                fontSize=10,
                leading=12,
                alignment=TA_CENTER,
                textColor=colors.HexColor("#4F46E5"),
                spaceAfter=2,
                shaping=shaping_value,
            ),
            "title": ParagraphStyle(
                "LessonTitle",
                parent=sample["Title"],
                fontName=bold_font_name,
                fontSize=20,
                leading=24,
                alignment=TA_CENTER,
                textColor=colors.HexColor("#111827"),
                spaceAfter=4,
                shaping=shaping_value,
            ),
            "meta_label": ParagraphStyle(
                "MetaLabel",
                parent=sample["Normal"],
                fontName=bold_font_name,
                fontSize=8.5,
                leading=11,
                textColor=colors.HexColor("#374151"),
                shaping=shaping_value,
            ),
            "meta_value": ParagraphStyle(
                "MetaValue",
                parent=sample["Normal"],
                fontName=font_name,
                fontSize=8.5,
                leading=11,
                textColor=colors.HexColor("#111827"),
                shaping=shaping_value,
            ),
            "heading": ParagraphStyle(
                "LessonHeading",
                parent=sample["Heading2"],
                fontName=bold_font_name,
                fontSize=12.5,
                leading=16,
                textColor=colors.HexColor("#312E81"),
                spaceBefore=7,
                spaceAfter=4,
                keepWithNext=True,
                shaping=shaping_value,
            ),
            "body": ParagraphStyle(
                "LessonBody",
                parent=sample["BodyText"],
                **base,
                fontSize=10.2,
                spaceAfter=4,
                alignment=TA_LEFT,
                shaping=shaping_value,
            ),
            "bullet": ParagraphStyle(
                "LessonBullet",
                parent=sample["BodyText"],
                **base,
                fontSize=10.2,
                leftIndent=6 * mm,
                firstLineIndent=-3.5 * mm,
                bulletIndent=2 * mm,
                spaceAfter=2.5,
                shaping=shaping_value,
            ),
        }

    def _metadata_table(
        self,
        metadata: LessonPdfMetadata,
        styles: dict[str, ParagraphStyle],
        labels: dict[str, str],
    ) -> Table:
        duration_value = (
            f"{metadata.duration_minutes} {labels['minutes']}" if metadata.duration_minutes else ""
        )
        day_value = self._localized_day_value(metadata.day_title, metadata.preferred_language)
        rows = [
            (labels["teacher"], metadata.teacher_name),
            (labels["school"], metadata.school_name),
            (labels["grade"], metadata.grade),
            (labels["subject"], metadata.subject),
            (labels["duration"], duration_value),
            (labels["book"], metadata.book_title),
            (labels["chapter"], metadata.chapter_title or metadata.section_title),
            (labels["section"], metadata.section_title if metadata.section_title != metadata.chapter_title else ""),
            (labels["day"], day_value),
            (labels["book_pages"], metadata.pages),
            (labels["lesson_type"], labels["customized"] if metadata.is_customized else labels["generated"]),
        ]
        filtered_rows = [(label, value) for label, value in rows if str(value or "").strip()]
        data = [
            [
                Paragraph(escape(label), styles["meta_label"]),
                Paragraph(escape(str(value)), styles["meta_value"]),
            ]
            for label, value in filtered_rows
        ]
        table = Table(data, colWidths=[36 * mm, 132 * mm], hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF2FF")),
                    ("BACKGROUND", (1, 0), (1, -1), colors.HexColor("#F9FAFB")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#E5E7EB")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return table

    @staticmethod
    def _localized_day_value(day_title: str, preferred_language: str) -> str:
        value = (day_title or "").strip()
        if language_key(preferred_language) != "hindi":
            return value
        match = re.fullmatch(r"Day\s+(\d+)", value, flags=re.IGNORECASE)
        return f"दिन {match.group(1)}" if match else value

    def _lesson_flowables(self, text: str, styles: dict[str, ParagraphStyle]) -> list:
        flowables: list = []
        pending_paragraph: list[str] = []

        def flush_paragraph() -> None:
            if not pending_paragraph:
                return
            combined = " ".join(item.strip() for item in pending_paragraph if item.strip())
            pending_paragraph.clear()
            if combined:
                flowables.append(Paragraph(self._paragraph_markup(combined), styles["body"]))

        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if not line:
                flush_paragraph()
                flowables.append(Spacer(1, 1.8 * mm))
                continue

            # WhatsApp formatter uses a single pair of asterisks for bold
            # section headings, for example: *📚 Lesson Overview*.
            whatsapp_heading = self._WHATSAPP_BOLD_LINE_RE.fullmatch(line)
            if whatsapp_heading:
                flush_paragraph()
                heading = self._strip_unsupported_symbols(
                    whatsapp_heading.group(1).strip()
                )
                if heading:
                    flowables.append(
                        Paragraph(
                            self._paragraph_markup(heading),
                            styles["heading"],
                        )
                    )
                continue

            markdown_heading = self._MARKDOWN_HEADING_RE.match(line)
            if markdown_heading:
                flush_paragraph()
                heading = markdown_heading.group(1).strip()
                flowables.append(Paragraph(self._paragraph_markup(heading), styles["heading"]))
                continue

            bullet = self._BULLET_RE.match(line)
            if bullet:
                flush_paragraph()
                bullet_text = bullet.group(1).strip()
                flowables.append(
                    Paragraph(
                        self._paragraph_markup(bullet_text),
                        styles["bullet"],
                        bulletText="•",
                    )
                )
                continue

            if self._looks_like_heading(line):
                flush_paragraph()
                flowables.append(Paragraph(self._paragraph_markup(line.rstrip(":")), styles["heading"]))
                continue

            pending_paragraph.append(line)

        flush_paragraph()
        if not flowables:
            flowables.append(Paragraph(self._paragraph_markup(text), styles["body"]))
        return flowables

    @staticmethod
    def _looks_like_heading(line: str) -> bool:
        clean = line.strip()
        if clean.endswith(":") and len(clean) <= 90:
            return True
        words = clean.split()
        if 1 <= len(words) <= 8 and len(clean) <= 72:
            letters = [ch for ch in clean if ch.isalpha()]
            if letters and sum(ch.isupper() for ch in letters) / len(letters) >= 0.7:
                return True
        return False

    def _paragraph_markup(self, text: str) -> str:
        clean = self._strip_unsupported_symbols(text)
        # Preserve lightweight Markdown emphasis without allowing arbitrary XML.
        escaped = escape(clean)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
        return escaped

    @staticmethod
    def _normalize_text(value: str) -> str:
        return (value or "").replace("\r\n", "\n").replace("\r", "\n").strip()

    @staticmethod
    def _strip_unsupported_symbols(value: str) -> str:
        """Remove decorative emoji while preserving Hindi and math symbols."""
        result: list[str] = []
        decorative_symbols = {
            "⏱",
            "⭐",
            "✅",
        }

        for char in value:
            code = ord(char)
            category = unicodedata.category(char)

            # Emoji variation selector and zero-width joiner. Once the emoji
            # components are removed these should not be left behind.
            if char in {"\ufe0f", "\u200d"}:
                continue

            # Symbols seen in lesson-plan headings that may not be covered by the
            # selected text font.
            if char in decorative_symbols:
                continue

            # Most modern emoji, including 📚 🎯 🧰 👩 🏫 🏠.
            if 0x1F000 <= code <= 0x1FAFF:
                continue

            # Miscellaneous decorative/dingbat symbols. This range does not remove
            # the common mathematical operators we need to preserve: ≠ ≤ ≥ √ ± × ÷.
            if category == "So" and 0x2600 <= code <= 0x27BF:
                continue

            result.append(char)

        return "".join(result).strip()

    def _build_filename(self, metadata: LessonPdfMetadata) -> str:
        topic = metadata.chapter_title or metadata.section_title or metadata.book_title or "Lesson"
        day = metadata.day_title or ""
        custom = " Customized" if metadata.is_customized else ""
        raw = f"{topic} {day}{custom} Lesson Plan".strip()
        ascii_safe = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
        source = ascii_safe or "Teacher Helper Lesson Plan"
        source = re.sub(r"[^A-Za-z0-9._ -]+", "", source)
        source = re.sub(r"\s+", "_", source).strip("._-")
        return f"{source[:90] or 'Teacher_Helper_Lesson_Plan'}.pdf"

    @staticmethod
    def _draw_page_decorations(
        canvas,
        doc,
        *,
        font_name: str,
        bold_font_name: str,
        page_label: str = "Page",
    ) -> None:
        canvas.saveState()
        page_width, _ = A4
        canvas.setStrokeColor(colors.HexColor("#E5E7EB"))
        canvas.setLineWidth(0.5)
        canvas.line(doc.leftMargin, 12 * mm, page_width - doc.rightMargin, 12 * mm)
        canvas.setFont(font_name, 8)
        canvas.setFillColor(colors.HexColor("#6B7280"))
        canvas.drawString(doc.leftMargin, 7.5 * mm, "Teacher Helper")
        canvas.setFont(bold_font_name, 8)
        canvas.drawRightString(page_width - doc.rightMargin, 7.5 * mm, f"{page_label} {doc.page}")
        canvas.restoreState()
