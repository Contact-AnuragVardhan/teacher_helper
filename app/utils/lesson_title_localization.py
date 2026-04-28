from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.language import language_key


_DATE_SUFFIX_RE = re.compile(
    r"^(?P<base>.*?)(?P<suffix>_\d{1,2}_[A-Za-z]{3,9}_\d{4}(?:[-_]\d+|-)?$)"
)
_COUNTER_SUFFIX_RE = re.compile(r"^(?P<base>.*?)(?P<suffix>[-_]\d+)$")
_SHARED_PREFIX_RE = re.compile(r"^(?P<prefix>\*\s*)(?P<title>.*)$")


@dataclass(frozen=True)
class LessonTitleParts:
    prefix: str
    base: str
    suffix: str


_ROMAN_TO_DEVANAGARI_PHRASES = {
    "jhansi ki rani": "झाँसी की रानी",
    "jhansi rani": "झाँसी की रानी",
    "rani of jhansi": "झाँसी की रानी",
    "rani lakshmibai": "रानी लक्ष्मीबाई",
    "rani laxmi bai": "रानी लक्ष्मीबाई",
    "rani lakshmi bai": "रानी लक्ष्मीबाई",
    "reedh ki haddi": "रीढ़ की हड्डी",
    "reed ki haddi": "रीढ़ की हड्डी",
    "spine": "रीढ़ की हड्डी",
    "backbone": "रीढ़ की हड्डी",
    "components of food": "भोजन के घटक",
    "plant life": "पौधों का जीवन",
    "plants": "पौधे",
    "plant": "पौधा",
    "fractions": "भिन्न",
    "fraction": "भिन्न",
    "sets": "समुच्चय",
    "earthquake": "भूकंप",
    "earthquakes": "भूकंप",
    "gravity": "गुरुत्वाकर्षण",
    "mass and weight": "द्रव्यमान और भार",
    "food": "भोजन",
    "water": "पानी",
    "air": "हवा",
    "weather": "मौसम",
    "environment": "पर्यावरण",
    "spring": "वसंत",
    "science": "विज्ञान",
    "math": "गणित",
    "maths": "गणित",
    "mathematics": "गणित",
    "english": "अंग्रेज़ी",
    "hindi": "हिंदी",
    "social science": "सामाजिक विज्ञान",
    "social studies": "सामाजिक विज्ञान",
    "history": "इतिहास",
    "geography": "भूगोल",
    "economics": "अर्थशास्त्र",
    "civics": "नागरिक शास्त्र",
}

_DEVANAGARI_TO_ROMAN_PHRASES = {
    "झाँसी की रानी": "Jhansi Ki Rani",
    "झांसी की रानी": "Jhansi Ki Rani",
    "झाँसीकीरानी": "Jhansi Ki Rani",
    "झांसीकीरानी": "Jhansi Ki Rani",
    "रानी लक्ष्मीबाई": "Rani Lakshmibai",
    "रानीलक्ष्मीबाई": "Rani Lakshmibai",
    "रीढ़ की हड्डी": "Reedh Ki Haddi",
    "रीढ़ की हड्डी": "Reedh Ki Haddi",
    "रीढ़कीहड्डी": "Reedh Ki Haddi",
    "भोजन के घटक": "Components Of Food",
    "भोजनकेघटक": "Components Of Food",
    "पौधों का जीवन": "Plant Life",
    "पौधोंकाजीवन": "Plant Life",
    "पौधे": "Plants",
    "पौधा": "Plant",
    "भिन्न": "Fractions",
    "समुच्चय": "Sets",
    "भूकंप": "Earthquake",
    "गुरुत्वाकर्षण": "Gravity",
    "द्रव्यमान और भार": "Mass And Weight",
    "द्रव्यमानऔरभार": "Mass And Weight",
    "भोजन": "Food",
    "पानी": "Water",
    "हवा": "Air",
    "मौसम": "Weather",
    "पर्यावरण": "Environment",
    "वसंत": "Spring",
    "विज्ञान": "Science",
    "गणित": "Mathematics",
    "अंग्रेज़ी": "English",
    "अंग्रेजी": "English",
    "हिंदी": "Hindi",
    "सामाजिक विज्ञान": "Social Science",
    "सामाजिकविज्ञान": "Social Science",
    "इतिहास": "History",
    "भूगोल": "Geography",
    "अर्थशास्त्र": "Economics",
    "नागरिक शास्त्र": "Civics",
    "नागरिकशास्त्र": "Civics",
}

_ROMAN_WORD_TO_DEVANAGARI = {
    "and": "और",
    "aur": "और",
    "of": "का",
    "ki": "की",
    "ke": "के",
    "ka": "का",
    "in": "में",
    "me": "में",
    "mein": "में",
    "jhansi": "झाँसी",
    "rani": "रानी",
    "lakshmibai": "लक्ष्मीबाई",
    "laxmibai": "लक्ष्मीबाई",
    "laxmi": "लक्ष्मी",
    "lakshmi": "लक्ष्मी",
    "bai": "बाई",
    "reedh": "रीढ़",
    "reed": "रीढ़",
    "haddi": "हड्डी",
    "earthquake": "भूकंप",
    "earthquakes": "भूकंप",
    "gravity": "गुरुत्वाकर्षण",
    "sets": "समुच्चय",
    "set": "समुच्चय",
    "sparsh": "स्पर्श",
    "hindi": "हिंदी",
    "lesson": "पाठ",
    "ganit": "गणित",
    "vigyan": "विज्ञान",
    "samajik": "सामाजिक",
    "angrezi": "अंग्रेज़ी",
}

_DEVANAGARI_WORD_TO_ROMAN = {
    "और": "And",
    "का": "Ka",
    "की": "Ki",
    "के": "Ke",
    "में": "Mein",
    "झाँसी": "Jhansi",
    "झांसी": "Jhansi",
    "रानी": "Rani",
    "लक्ष्मीबाई": "Lakshmibai",
    "रीढ़": "Reedh",
    "रीढ़": "Reedh",
    "हड्डी": "Haddi",
    "गणित": "Ganit",
    "विज्ञान": "Vigyan",
    "सामाजिक": "Samajik",
    "अंग्रेज़ी": "Angrezi",
    "अंग्रेजी": "Angrezi",
}


_CONSONANTS = {
    "क": "k",
    "ख": "kh",
    "ग": "g",
    "घ": "gh",
    "ङ": "ng",
    "च": "ch",
    "छ": "chh",
    "ज": "j",
    "झ": "jh",
    "ञ": "ny",
    "ट": "t",
    "ठ": "th",
    "ड": "d",
    "ढ": "dh",
    "ण": "n",
    "त": "t",
    "थ": "th",
    "द": "d",
    "ध": "dh",
    "न": "n",
    "प": "p",
    "फ": "ph",
    "ब": "b",
    "भ": "bh",
    "म": "m",
    "य": "y",
    "र": "r",
    "ल": "l",
    "व": "v",
    "श": "sh",
    "ष": "sh",
    "स": "s",
    "ह": "h",
    "ळ": "l",
}

_INDEPENDENT_VOWELS = {
    "अ": "a",
    "आ": "a",
    "इ": "i",
    "ई": "i",
    "उ": "u",
    "ऊ": "u",
    "ए": "e",
    "ऐ": "ai",
    "ओ": "o",
    "औ": "au",
    "ऋ": "ri",
}

_MATRAS = {
    "ा": "a",
    "ि": "i",
    "ी": "i",
    "ु": "u",
    "ू": "u",
    "े": "e",
    "ै": "ai",
    "ो": "o",
    "ौ": "au",
    "ृ": "ri",
}

_DIACRITICS = {"ं": "n", "ँ": "n", "ः": "h", "़": ""}


def localize_lesson_display_title(lesson_name: str, topic: str | None, target_language: str | None) -> str:
    """Return a display-only lesson title localized for the viewer's current profile language.

    The stored lesson_name is not changed. Only the topic/base part is localized.
    Generated suffixes such as _28_Apr_2026, _28_April_2026, -1, or -3 are preserved.
    """
    title = (lesson_name or "").strip()
    if not title:
        return title

    parts = _split_title_parts(title)
    target = language_key(target_language)

    source_text = _best_source_text(parts.base, topic)
    if target == "hindi":
        localized_base = _to_devanagari_title_base(source_text)
    else:
        localized_base = _to_hinglish_title_base(source_text)

    localized_base = localized_base.strip() or parts.base
    return f"{parts.prefix}{localized_base}{parts.suffix}"


def _split_title_parts(title: str) -> LessonTitleParts:
    prefix = ""
    match = _SHARED_PREFIX_RE.match(title)
    if match:
        prefix = match.group("prefix")
        title = match.group("title")

    date_match = _DATE_SUFFIX_RE.match(title)
    if date_match:
        return LessonTitleParts(
            prefix=prefix,
            base=(date_match.group("base") or "").strip(),
            suffix=date_match.group("suffix") or "",
        )

    counter_match = _COUNTER_SUFFIX_RE.match(title)
    if counter_match:
        base = (counter_match.group("base") or "").strip()
        suffix = counter_match.group("suffix") or ""
        # Treat -1 / -2 duplicate markers as suffixes, but do not turn a pure number
        # title into an empty localized base.
        if base:
            return LessonTitleParts(prefix=prefix, base=base, suffix=suffix)

    return LessonTitleParts(prefix=prefix, base=title, suffix="")


def _best_source_text(name_base: str, topic: str | None) -> str:
    topic_value = re.sub(r"\s+", " ", (topic or "").strip())
    if topic_value:
        return topic_value

    # Generated lesson names are compact. Split Roman CamelCase for better lookup.
    return _with_camelcase_spaces(name_base)


def _to_devanagari_title_base(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "").strip())
    if not cleaned:
        return "पाठ"

    if _has_devanagari(cleaned):
        devanagari = _normalize_devanagari_lookup(cleaned)
        if devanagari in _DEVANAGARI_TO_ROMAN_PHRASES:
            # Already a known Devanagari title; use a readable canonical value.
            cleaned = _canonical_devanagari_phrase(devanagari)
        compact = re.sub(r"[^0-9\u0900-\u097F]+", "", cleaned)
        return compact[:48] or "पाठ"

    normalized = _normalize_roman_lookup(cleaned)
    phrase = _ROMAN_TO_DEVANAGARI_PHRASES.get(normalized)
    if phrase:
        return _compact_devanagari(phrase)

    words = _roman_words(cleaned)
    converted_words = [_ROMAN_WORD_TO_DEVANAGARI.get(word.casefold()) for word in words]
    if words and all(converted_words):
        return _compact_devanagari(" ".join(converted_words))

    transliterated = _roman_to_devanagari_fallback(cleaned)
    return _compact_devanagari(transliterated)[:48] or "पाठ"


def _to_hinglish_title_base(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "").strip())
    if not cleaned:
        return "Lesson"

    if _has_devanagari(cleaned):
        normalized_devanagari = _normalize_devanagari_lookup(cleaned)
        phrase = _DEVANAGARI_TO_ROMAN_PHRASES.get(normalized_devanagari)
        if phrase:
            return _compact_pascal_case(phrase)[:48] or "Lesson"

        words = re.findall(r"[\u0900-\u097F]+", cleaned)
        converted_words = [_DEVANAGARI_WORD_TO_ROMAN.get(word) for word in words]
        if words and all(converted_words):
            return _compact_pascal_case(" ".join(converted_words))[:48] or "Lesson"

        transliterated = _devanagari_to_hinglish_fallback(cleaned)
        return _compact_pascal_case(transliterated)[:48] or "Lesson"

    normalized = _normalize_roman_lookup(cleaned)
    phrase = _ROMAN_TO_DEVANAGARI_PHRASES.get(normalized)
    if phrase:
        roman_phrase = _DEVANAGARI_TO_ROMAN_PHRASES.get(_normalize_devanagari_lookup(phrase))
        if roman_phrase:
            return _compact_pascal_case(roman_phrase)[:48] or "Lesson"

    return cleaned[:48] or "Lesson"


def _canonical_devanagari_phrase(normalized_value: str) -> str:
    for key, roman_value in _DEVANAGARI_TO_ROMAN_PHRASES.items():
        if _normalize_devanagari_lookup(key) == normalized_value:
            normalized_roman = _normalize_roman_lookup(roman_value)
            return _ROMAN_TO_DEVANAGARI_PHRASES.get(normalized_roman, key)
    return normalized_value


def _compact_devanagari(value: str) -> str:
    return re.sub(r"[^0-9\u0900-\u097F]+", "", value or "")


def _compact_pascal_case(value: str) -> str:
    words = re.findall(r"[0-9A-Za-z]+", _with_camelcase_spaces(value or ""))
    pieces: list[str] = []
    for word in words:
        if word.isupper() and len(word) > 1:
            pieces.append(word)
        else:
            pieces.append(word[:1].upper() + word[1:].lower())
    return "".join(pieces)


def _with_camelcase_spaces(value: str) -> str:
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value or "")
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", value)
    return value


def _normalize_roman_lookup(value: str) -> str:
    value = _with_camelcase_spaces(value)
    value = re.sub(r"[^0-9A-Za-z]+", " ", value)
    return re.sub(r"\s+", " ", value).strip().casefold()


def _normalize_devanagari_lookup(value: str) -> str:
    value = re.sub(r"[\u093C]", "", value or "")
    value = re.sub(r"[^\u0900-\u097F]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _roman_words(value: str) -> list[str]:
    return re.findall(r"[0-9A-Za-z]+", _with_camelcase_spaces(value or ""))


def _has_devanagari(value: str) -> bool:
    return bool(re.search(r"[\u0900-\u097F]", value or ""))


def _devanagari_to_hinglish_fallback(value: str) -> str:
    pieces: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]

        if char in _CONSONANTS:
            consonant = _CONSONANTS[char]
            next_char = value[index + 1] if index + 1 < len(value) else ""
            if next_char == "्":
                pieces.append(consonant)
                index += 2
                continue
            if next_char in _MATRAS:
                pieces.append(consonant + _MATRAS[next_char])
                index += 2
                continue
            pieces.append(consonant + "a")
            index += 1
            continue

        if char in _INDEPENDENT_VOWELS:
            pieces.append(_INDEPENDENT_VOWELS[char])
        elif char in _MATRAS:
            pieces.append(_MATRAS[char])
        elif char in _DIACRITICS:
            pieces.append(_DIACRITICS[char])
        elif char.isspace() or char in {"-", "_", "/"}:
            pieces.append(" ")
        elif char.isalnum():
            pieces.append(char)
        else:
            pieces.append(" ")
        index += 1

    rough = "".join(pieces)
    rough = re.sub(r"\ba([aeiou])", r"\1", rough)
    words = []
    for word in rough.split():
        # Simple final-schwa cleanup: पाठ -> path, गणित -> ganit, etc.
        if len(word) > 2 and word.endswith("a"):
            word = word[:-1]
        words.append(word)
    return " ".join(words)


def _roman_to_devanagari_fallback(value: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+|\s+|[^A-Za-z0-9\s]+", _with_camelcase_spaces(value or ""))
    converted: list[str] = []
    for token in tokens:
        if token.isspace():
            converted.append(" ")
            continue
        if re.fullmatch(r"[0-9]+", token):
            converted.append(token)
            continue
        if not re.fullmatch(r"[A-Za-z]+", token):
            continue
        lower = token.casefold()
        if lower in _ROMAN_WORD_TO_DEVANAGARI:
            converted.append(_ROMAN_WORD_TO_DEVANAGARI[lower])
        else:
            converted.append(_roman_word_to_devanagari(lower))
    return re.sub(r"\s+", " ", "".join(converted)).strip()


def _roman_word_to_devanagari(word: str) -> str:
    # Small phonetic fallback for unknown Hinglish/English words. This is only for
    # display labels, so prefer a readable Devanagari approximation over failing.
    vowels = {
        "aa": "ा",
        "ai": "ै",
        "au": "ौ",
        "ee": "ी",
        "ii": "ी",
        "oo": "ू",
        "ou": "ौ",
        "a": "",
        "e": "े",
        "i": "ि",
        "o": "ो",
        "u": "ु",
    }
    consonants = {
        "chh": "छ",
        "kh": "ख",
        "gh": "घ",
        "ch": "च",
        "jh": "झ",
        "th": "थ",
        "dh": "ध",
        "ph": "फ",
        "bh": "भ",
        "sh": "श",
        "ksh": "क्ष",
        "gy": "ज्ञ",
        "ny": "न्य",
        "ng": "ंग",
        "k": "क",
        "g": "ग",
        "c": "क",
        "j": "ज",
        "t": "त",
        "d": "द",
        "n": "न",
        "p": "प",
        "f": "फ",
        "b": "ब",
        "m": "म",
        "y": "य",
        "r": "र",
        "l": "ल",
        "v": "व",
        "w": "व",
        "s": "स",
        "h": "ह",
        "z": "ज",
        "q": "क",
        "x": "क्स",
    }
    independent_vowels = {
        "aa": "आ",
        "ai": "ऐ",
        "au": "औ",
        "ee": "ई",
        "ii": "ई",
        "oo": "ऊ",
        "ou": "औ",
        "a": "अ",
        "e": "ए",
        "i": "इ",
        "o": "ओ",
        "u": "उ",
    }

    output: list[str] = []
    index = 0
    previous_was_consonant = False
    while index < len(word):
        matched_vowel = None
        for size in (2, 1):
            candidate = word[index : index + size]
            if candidate in vowels:
                matched_vowel = candidate
                break
        if matched_vowel:
            if previous_was_consonant:
                output.append(vowels[matched_vowel])
            else:
                output.append(independent_vowels[matched_vowel])
            previous_was_consonant = False
            index += len(matched_vowel)
            continue

        matched_consonant = None
        for size in (3, 2, 1):
            candidate = word[index : index + size]
            if candidate in consonants:
                matched_consonant = candidate
                break
        if matched_consonant:
            if previous_was_consonant:
                output.append("्")
            output.append(consonants[matched_consonant])
            previous_was_consonant = True
            index += len(matched_consonant)
            continue

        index += 1

    return "".join(output) or word
