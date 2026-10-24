"""Deterministic Egyptian Arabic language and intent helpers."""

import re
from typing import Any, Dict, Optional

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

_NUMBER_WORDS = {
    "الف": 1000,
    "ألف": 1000,
    "ألفين": 2000,
    "مليون": 1_000_000,
    "مليونين": 2_000_000,
    "نص مليون": 500_000,
    "مية": 100,
    "مائه": 100,
    "مئة": 100,
    "عشر تلاف": 10_000,
    "عشرة الاف": 10_000,
    "عشرة آلاف": 10_000,
    "خمستاشر": 15,
    "خمستاشر ألف": 15_000,
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

_PRICE_PATTERN = re.compile(
    r"(?:بسعر\s+)?(?:أقل\s+من|اقل\s+من|تحت|بحد\s+أقصى|بحد\s+اقصى|"
    r"ميزانيتي|مش\s+أكتر\s+من|مش\s+اكتر\s+من|ب)\s+"
    r"([0-9٠-٩][0-9٠-٩,٬.]*\s*(?:ألف|الف|ألفين|مليون|مليونين)?|"
    r"(?:ألفين|ألف|الف|خمستاشر(?:\s+ألف)?|نص مليون|عشر تلاف|عشرة آلاف|عشرة الاف))"
    r"\s*(?:جنيه|جنية|egp)?",
    re.IGNORECASE,
)


def detect_language(text: str) -> str:
    """Return ``ar`` when at least 30% of alphabetic chars are Arabic."""
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
    for word, factor in (
        ("مليونين", 2_000_000),
        ("مليون", 1_000_000),
        ("ألفين", 2_000),
        ("ألف", 1_000),
        ("الف", 1_000),
    ):
        if word in normalized:
            normalized = normalized.replace(word, "").strip()
            multiplier = factor
            break
    if not normalized:
        return float(multiplier)
    try:
        return float(normalized.replace(",", "").replace("٬", ""))
    except ValueError:
        return None


def parse_arabic_intent(message: str) -> Dict[str, Any]:
    """Parse an Egyptian Arabic product query and optional maximum price."""
    msg = message.strip()
    max_price: Optional[float] = None
    query = msg
    match = _PRICE_PATTERN.search(msg)
    if match:
        max_price = _parse_number(match.group(1))
        query = f"{msg[:match.start()]} {msg[match.end():]}"
    else:
        standalone = re.search(
            r"([0-9٠-٩][0-9٠-٩,٬.]*|ألفين|ألف|الف|خمستاشر(?:\s+ألف)?|نص مليون|عشر تلاف|عشرة آلاف)"
            r"\s*(?:جنيه|جنية|egp)?\s*$",
            msg,
            re.IGNORECASE,
        )
        if standalone:
            max_price = _parse_number(standalone.group(1))
            query = msg[:standalone.start()]

    query = re.sub(r"\s+", " ", query).strip()
    query = re.sub(r"^(?:عايز|عايزة|محتاج|محتاجة|هات|اديني|ممكن)\s+", "", query)
    return {"query": query, "max_price": max_price}


def translate_query_for_search(query: str) -> str:
    """Translate known Arabic product terms while preserving brands and specs."""
    translated = query
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
    normalized = re.sub(r"\s+", " ", message.strip())
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
