"""Small, dependency-free response localization for the chatbot."""

MESSAGES = {
    "en": {
        "no_results": (
            "I couldn't find any products matching '{query}'{price_filter}. "
            "Try a different search term."
        ),
        "found_results": (
            "I found {count} product{plural} matching "
            "'{query}'{price_filter}:"
        ),
        "added_to_feed": (
            "I've added '{title}' to your tracking feed. I'll monitor the price "
            "and notify you when it changes."
        ),
        "no_search_results": "No search results found to add to your feed.",
        "add_failed": (
            "Sorry, I couldn't add this to your feed at the moment. "
            "Please try again later."
        ),
        "insufficient_credits": (
            "Insufficient credits: {detail}. Upgrade your plan "
            "to continue."
        ),
        "empty_query": "Please enter a product to search for.",
        "price_filter": " under {max_price:g} EGP",
        "price_min": " over {min_price:g} EGP",
        "price_range": " between {min_price:g} and {max_price:g} EGP",
    },
    "ar": {
        "no_results": 'مش لاقي منتجات لـ "{query}"{price_filter}. جرب كلمات تانية.',
        "found_results": 'لقيت {count} منتج{plural} لـ "{query}"{price_filter}:',
        "added_to_feed": 'تمام! أضفت "{title}" للمتابعة. هنبلغك لما السعر يتغير 👍',
        "no_search_results": "مفيش نتائج بحث لإضافتها.",
        "add_failed": "معلش، مقدرتش أضيف المنتج ده دلوقتي. جرب تاني بعدين.",
        "insufficient_credits": "رصيدك مش كفاية: {detail}. ممكن تطور باقتك.",
        "empty_query": "اكتب اسم المنتج اللي عايز تدور عليه.",
        "price_filter": " بأقل من {max_price:g} جنيه",
        "price_min": " بأكتر من {min_price:g} جنيه",
        "price_range": " من {min_price:g} لـ {max_price:g} جنيه",
    },
}


def format_message(key: str, language: str = "en", **kwargs: object) -> str:
    """Format a localized message, falling back to English for unknown locales."""
    template = MESSAGES.get(language, MESSAGES["en"]).get(key)
    if template is None:
        raise KeyError(f"Unknown chatbot message key: {key}")
    return template.format(**kwargs)
