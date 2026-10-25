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

# The alef in these keys is spelled two ways: bare, or with a hamza above it.
# Queries carry both, so the hamza variant is folded onto the bare alef on the
# input side (see _parse_number) and the keys are folded the same way here.
# Without the fold, a key carrying a hamza alef is unreachable and its scale
# word silently stops multiplying: the two-thousand word reads as one thousand.
_HAMZA_ALEF = "\u0623"  # alef with hamza above
_BARE_ALEF = "\u0627"  # alef


_NUMBER_WORDS_BY_SPELLING = {
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
    r"ميزانيتي|مش\s+أكتر\s+من|مش\s+اكتر\s+من|(?<![\u0600-\u06FF])ب)\s+"
    r"([0-9٠-٩][0-9٠-٩,٬.]*\s*(?:ألف|الف|ألفين|مليون|مليونين)?|"
    r"(?:ألفين|ألف|الف|خمستاشر(?:\s+ألف)?|نص مليون|عشر تلاف|عشرة آلاف|عشرة الاف))"
    r"\s*(?:جنيه|جنية|egp)?",
    re.IGNORECASE,
)


# Fold the table onto exactly the spelling the input is folded to, so every
# scale word stays reachable however its alef is written.
_NUMBER_WORDS = {
    word.replace(_HAMZA_ALEF, _BARE_ALEF): value
    for word, value in _NUMBER_WORDS_BY_SPELLING.items()
}


def detect_language(text: str) -> str:
    """Return ``ar`` when at least 30% of alphabetic chars are Arabic."""
    arabic_count = len(_ARABIC_CHAR_RE.findall(text))
    total_alpha = sum(1 for char in text if char.isalpha())
    return "ar" if total_alpha and arabic_count / total_alpha >= 0.3 else "en"


def _parse_number(value: str) -> Optional[float]:
    """Parse Arabic or Latin digits and common Egyptian number words."""
    normalized = value.translate(_EASTERN_DIGITS).strip().lower()
    normalized = normalized.replace(_HAMZA_ALEF, _BARE_ALEF)
    normalized = re.sub(r"\s+", " ", normalized)
    if normalized in _NUMBER_WORDS:
        return float(_NUMBER_WORDS[normalized])

    # A price filter usually arrives with the number and its scale word in
    # one captured run ("12 alef-lam-fe"). ``_NUMBER_WORDS`` is the only place
    # that writes out every spelling each scale word is typed with, so the
    # scale word is looked up there instead of repeating a second list of
    # spellings here: a hardcoded list that missed one spelling turned 12000
    # into 12 EGP.
    parts = normalized.split(" ")
    for take in (2, 1):
        if len(parts) <= take:
            continue
        factor = _NUMBER_WORDS.get(" ".join(parts[-take:]))
        if factor is None:
            continue
        try:
            digits = float(" ".join(parts[:-take]).replace(",", ""))
        except ValueError:
            continue
        return digits * factor

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
    msg = message.strip().replace(_HAMZA_ALEF, _BARE_ALEF)
    max_price: Optional[float] = None
    query = msg
    match = _PRICE_PATTERN.search(msg)
    if match:
        # The alternation stops at the first scale-word spelling that fits, so
        # a longer one is cut short: the two-thousand word is also the one-
        # thousand word with a suffix, and matching the shorter form turns 2000
        # into 1000. When nothing else was consumed after the captured run,
        # any letters glued to it belong to the same word, so the capture is
        # extended to the end of that word. A space-separated currency word
        # has already been consumed by the pattern, so it is never swallowed.
        end = match.end(1)
        if match.end() == end:
            while end < len(msg) and _ARABIC_CHAR_RE.match(msg[end]):
                end += 1
        max_price = _parse_number(msg[match.start(1) : end])
        query = f"{msg[:match.start()]} {msg[max(match.end(), end):]}"
    else:
        standalone = re.search(
            r"([0-9٠-٩][0-9٠-٩,٬.]*"
            r"|ألفين|ألف|الف|خمستاشر(?:\s+ألف)?|نص مليون|عشر تلاف|عشرة آلاف)"
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
