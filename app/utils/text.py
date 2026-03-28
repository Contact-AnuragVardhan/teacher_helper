def clean_text(value: str | None) -> str:
    return (value or "").strip()


def normalize_choice(value: str | None) -> str:
    return clean_text(value).casefold()


def is_blank(value: str | None) -> bool:
    return clean_text(value) == ""
