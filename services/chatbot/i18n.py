"""Small, dependency-free response localization for the chatbot."""

MESSAGES = {
    "en": {
        "no_results": (
            "I couldn't find any products matching '{query}'{price_filter}. "
            "Try a different search term."
        ),
        "found_results": (
            "I found {count} product{plural} matching " "'{query}'{price_filter}:"
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
            "Insufficient credits: {detail}. Upgrade your plan " "to continue."
        ),
        "fair_use_cap": (
            "You're tracking {active} of {cap} products, the most one account "
            "can track. Remove one from your feed to add this one."
        ),
        "fair_use_cap_plain": (
            "You've reached the most products one account can track. Remove one "
            "from your feed to add this one."
        ),
        "creation_rate_limited": (
            "You're adding products a little fast. Try again in {seconds} seconds."
        ),
        "creation_rate_limited_plain": (
            "You're adding products a little fast. Try again in a moment."
        ),
        "already_tracking": "You're already tracking '{title}'.",
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
        "fair_use_cap": (
            "انت بتتابع {active} من {cap} منتج، ودي أقصى حاجة للحساب. "
            "شيل منتج من المتابعة عشان تضيف ده."
        ),
        "fair_use_cap_plain": (
            "وصلت لأقصى عدد منتجات تقدر تتابعه. شيل منتج من المتابعة عشان تضيف ده."
        ),
        "creation_rate_limited": (
            "بتضيف منتجات بسرعة شوية. جرب تاني بعد {seconds} ثانية."
        ),
        "creation_rate_limited_plain": "بتضيف منتجات بسرعة شوية. جرب تاني كمان شوية.",
        "already_tracking": 'انت بتتابع "{title}" بالفعل.',
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
