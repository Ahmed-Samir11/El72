"""Deterministic Egyptian Arabic language and intent helpers."""

import re
import unicodedata
from typing import Any, Dict, Optional


def strip_arabic_marks(text: str) -> str:
    """Drop Arabic diacritics and presentation marks from [text].

    Keyboards emit combining marks inside ordinary words ("alif" typed as
    ``a`` ``f`` + U+064F), which breaks every word-based lookup below. They
    carry no meaning for parsing, so all entry points normalize them away first.
    """
    return "".join(
        char for char in text if unicodedata.category(char) not in ("Mn", "Mc", "Me")
    )


_ARABIC_CHAR_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F]")
_EASTERN_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٬٫", "0123456789,.")

PRODUCT_TRANSLATIONS = {
    "شاشات": "monitors",
    "شاشة": "monitor",
    "لابتوب": "laptop",
    "لاب توب": "laptop",
    "كمبيوتر": "computer",
    "موبايلات": "mobile phones",
    "موبايل": "mobile phone",
    "تليفون": "phone",
    "تليفونات": "phones",
    "سماعات": "headphones",
    "سماعة": "headphone",
    "ماوس": "mouse",
    "كيبورد": "keyboard",
    "طابعة": "printer",
    "راوتر": "router",
    "هارد": "hard drive",
    "فلاشة": "flash drive",
    "شاحن": "charger",
    "باور بانك": "power bank",
    "كاميرا": "camera",
    "تابلت": "tablet",
    "تلفزيون": "television",
    "تكييف": "air conditioner",
    "ثلاجة": "refrigerator",
    "غسالة": "washing machine",
    "بلايستيشن": "playstation",
    "إكس بوكس": "xbox",
    "جزمة": "shoes",
    "شنطة": "bag",
    "تيشيرت": "t-shirt",
    "بنطلون": "pants",
    "خلاط": "blender",
    "مكواة": "iron",
    "ميكروويف": "microwave",
    "مكتب": "desk",
    "كرسي": "chair",
    "مرتبة": "mattress",
    "سرير": "bed",
    "كتاب": "book",
    "كتب": "books",
}

# Scale words: a number written next to one of these is in thousands or
# millions. They are kept apart from the spelled-out values so a thousand
# cannot hide among the tens, and so "12 alf" reads as 12 x 1000 rather
# than as a bare 1000.
_MULTIPLIER_WORDS = {
    "الف": 1000,
    "ألف": 1000,
    "ألفين": 2000,
    "مليون": 1000000,
    "مليونين": 2000000,
    "أف": 1000,
}

# Spelled-out values, including the Egyptian contractions for hundreds.
_NUMBER_WORDS = {
    "نص مليون": 500000,
    "مية": 100,
    "مائه": 100,
    "مئة": 100,
    "عشر تلاف": 10000,
    "عشرة الاف": 10000,
    "عشرة آلاف": 10000,
    "خمستاشر": 15,
    "خمستاشر ألف": 15000,
    "خمسة عشر": 15,
    "عشرين": 20,
    "تلاتين": 30,
    "ثلاثين": 30,
    "اربعين": 40,
    "أربعين": 40,
    "خمسين": 50,
    "ستين": 60,
    "سبعين": 70,
    "تمانين": 80,
    "ثمانين": 80,
    "تسعين": 90,
}

# Longest alternative first: "alfin" must win before "alf", and a spelled
# number before the bare scale word inside it.
_SCALE = "|".join(sorted(_MULTIPLIER_WORDS, key=len, reverse=True))
_SPOKEN = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))

# One price amount, in either shape: digits with an optional scale word, or
# a spelled-out number. Shared by the "under X" pattern and the trailing-value
# pattern, so the two cannot drift apart.
_AMOUNT = rf"(?:[0-9٠-٩][0-9٠-٩,٬.]*\s*(?:{_SCALE})?" rf"|{_SPOKEN}|{_SCALE})"

_PRICE_PATTERN = re.compile(
    r"(?:بسعر\s+)?(?:أقل\s+من|اقل\s+من|تحت|بحد\s+أقصى|بحد\s+اقصى|"
    r"ميزانيتي|مش\s+أكتر\s+من|مش\s+اكتر\s+من|(?<![\u0600-\u06FF])ب)\s+"
    rf"({_AMOUNT})"
    r"\s*(?:جنيه|جنية|egp)?",
    re.IGNORECASE,
)

_STANDALONE_PRICE = re.compile(
    rf"({_AMOUNT})\s*(?:جنيه|جنية|egp)?\s*$",
    re.IGNORECASE,
)


def detect_language(text: str) -> str:
    """Return ``ar`` when at least 30% of alphabetic chars are Arabic."""
    text = strip_arabic_marks(text)
    arabic_count = len(_ARABIC_CHAR_RE.findall(text))
    total_alpha = sum(1 for char in text if char.isalpha())
    return "ar" if total_alpha and arabic_count / total_alpha >= 0.3 else "en"


def _parse_number(value: str) -> Optional[float]:
    """Parse Arabic or Latin digits and common Egyptian number words."""
    normalized = value.translate(_EASTERN_DIGITS).strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    if normalized in _NUMBER_WORDS:
        return float(_NUMBER_WORDS[normalized])

    multiplier = 1
    for word, factor in sorted(
        _MULTIPLIER_WORDS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if word in normalized:
            normalized = normalized.replace(word, "").strip()
            multiplier = factor
            break
    if not normalized:
        return float(multiplier)
    try:
        return float(normalized.replace(",", "").replace("٬", "")) * multiplier
    except ValueError:
        return None


def parse_arabic_intent(message: str) -> Dict[str, Any]:
    """Parse an Egyptian Arabic product query and optional maximum price."""
    msg = strip_arabic_marks(message).strip()
    max_price: Optional[float] = None
    query = msg
    match = _PRICE_PATTERN.search(msg)
    if match:
        max_price = _parse_number(match.group(1))
        query = f"{msg[:match.start()]} {msg[match.end():]}"
    else:
        standalone = _STANDALONE_PRICE.search(msg)
        if standalone:
            max_price = _parse_number(standalone.group(1))
            query = msg[: standalone.start()]

    query = re.sub(r"\s+", " ", query).strip()
    query = re.sub(r"^(?:عايز|عايزة|محتاج|محتاجة|هات|اديني|ممكن)\s+", "", query)
    return {"query": query, "max_price": max_price}


def translate_query_for_search(query: str) -> str:
    """Translate known Arabic product terms while preserving brands and specs."""
    translated = strip_arabic_marks(query)
    for arabic, english in sorted(
        PRODUCT_TRANSLATIONS.items(), key=lambda item: len(item[0]), reverse=True
    ):
        translated = re.sub(
            rf"(?<![\u0600-\u06FF]){re.escape(arabic)}(?![\u0600-\u06FF])",
            english,
            translated,
        )
    return re.sub(r"\s+", " ", translated).strip()


def parse_add_command(message: str) -> Optional[int]:
    """Return a one-based result index for an Arabic add-to-feed command."""
    normalized = re.sub(r"\s+", " ", strip_arabic_marks(message).strip())
    if not re.search(r"(?:أضف|اضف|تابع|متابعة|أتابع|اتابع)", normalized):
        return None
    number = re.search(r"(?:رقم\s*)?([0-9٠-٩]+)", normalized)
    if number:
        try:
            return int(number.group(1).translate(_EASTERN_DIGITS))
        except ValueError:
            return None
    if re.search(r"(?:الأول|الاول|أولى|اولى)", normalized):
        return 1
    if re.search(r"(?:التاني|الثاني|تانى|ثاني)", normalized):
        return 2
    return 1
