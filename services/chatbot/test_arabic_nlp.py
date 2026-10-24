"""Unit tests for Egyptian Arabic chatbot parsing."""

from services.chatbot.arabic_nlp import (
    detect_language,
    parse_add_command,
    parse_arabic_intent,
    translate_query_for_search,
)


def test_detects_arabic_and_english():
    assert detect_language("عايز شاشات 2k") == "ar"
    assert detect_language("gaming laptop under 50000") == "en"
    assert detect_language("عايز laptop") == "ar"


def test_parses_arabic_price_filters():
    assert parse_arabic_intent("شاشات أقل من 12 ألف") == {
        "query": "شاشات",
        "max_price": 12000.0,
    }
    assert parse_arabic_intent("لابتوب تحت 30000")["max_price"] == 30000.0
    assert parse_arabic_intent("موبايل بحد أقصى ١٥٠٠٠")["max_price"] == 15000.0
    assert parse_arabic_intent("شاشة ب ١٢٬٠٠٠ جنيه")["max_price"] == 12000.0
    assert parse_arabic_intent("سماعات أقل من ألفين")["max_price"] == 2000.0
    assert parse_arabic_intent("تابلت مش أكتر من عشر تلاف")["max_price"] == 10000.0


def test_translates_product_terms_and_preserves_specs():
    assert translate_query_for_search("شاشات 2k") == "monitors 2k"
    assert translate_query_for_search("لابتوب Lenovo Legion") == "laptop Lenovo Legion"


def test_parses_add_commands():
    assert parse_add_command("أضف الأول") == 1
    assert parse_add_command("أضف رقم 3") == 3
    assert parse_add_command("تابع ده") == 1
    assert parse_add_command("شاشات 2k") is None
