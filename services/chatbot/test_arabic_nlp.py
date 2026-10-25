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


def test_thousands_written_after_the_digits_scale_them():
    """ "بmonitor 12 أف" means 12 thousand, not a bare thousand.

    The trailing-value pattern used to match only the scale word, so the digits
    stayed in the query and the price collapsed to 1000.
    """
    assert parse_arabic_intent("بmonitor 12 أف")["max_price"] == 12000.0
    assert parse_arabic_intent("بmonitor 12 ألف")["max_price"] == 12000.0
    assert parse_arabic_intent("بmonitor 12 أف")["query"] == "بmonitor"


def test_a_standalone_thousand_word_is_a_price():
    """A chat that says only "أف" means one thousand pounds."""
    assert parse_arabic_intent("أف")["max_price"] == 1000.0
    assert parse_arabic_intent("بmonitor ب أف")["max_price"] == 1000.0


def test_scale_words_stay_out_of_the_spelled_number_table():
    """Thousands and millions are a scale, not one more spelled value.

    Mixing them into _NUMBER_WORDS is what made "12 alf" ambiguous: the bare
    word matched first and the digits were left behind.
    """
    from services.chatbot import arabic_nlp

    assert all(value >= 1000 for value in arabic_nlp._MULTIPLIER_WORDS.values())
    assert not arabic_nlp._MULTIPLIER_WORDS.keys() & arabic_nlp._NUMBER_WORDS.keys()
    assert all(" " not in word for word in arabic_nlp._MULTIPLIER_WORDS)


def test_translates_product_terms_and_preserves_specs():
    assert translate_query_for_search("شاشات 2k") == "monitors 2k"
    assert translate_query_for_search("لابتوب Lenovo Legion") == "laptop Lenovo Legion"


def test_parses_add_commands():
    assert parse_add_command("أضف الأول") == 1
    assert parse_add_command("أضف رقم 3") == 3
    assert parse_add_command("تابع ده") == 1
    assert parse_add_command("شاشات 2k") is None
