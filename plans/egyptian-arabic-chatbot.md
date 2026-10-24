# Plan: Egyptian Arabic Chatbot Support

## Goal

Enable a user to chat with the El72 chatbot in **Egyptian Arabic (عامية)** and
get correct search results, with the option to **add items to the tracker** or
**view their feed** — all while the bot responds in Egyptian Arabic.

Example flow:
```
User:  عايز شاشات 2k بسعر أقل من 12 ألف
Bot:   لقيت 4 منتجات لـ "شاشات 2k" بأقل من 12,000 جنيه:
       1. Samsung 27" 2K QHD — 8,999 جنيه (Amazon Egypt) [أضف للمتابعة]
       2. LG 32" 2K Monitor — 10,500 جنيه (Noon) [أضف للمتابعة]
       ...

User:  أضف الأول
Bot:   تمام! أضفت "Samsung 27" 2K QHD" للمتابعة. هنبلغك لما السعر يتغير 👍
```

---

## Approach

### Overview

The work is split across **3 layers** — all within the existing chatbot service
(`services/chatbot/`). No new services, no new streams, no schema changes.

```
┌─────────────────────────────────────────────────────┐
│ Layer 1: Language Detection & Arabic Intent Parsing  │
│  (search_service.py)                                 │
├─────────────────────────────────────────────────────┤
│ Layer 2: Arabic Bot Responses & Localized UX         │
│  (main.py, new i18n module)                          │
├─────────────────────────────────────────────────────┤
│ Layer 3: Arabic Search Query Translation             │
│  (search_service.py — query preprocessor)            │
└─────────────────────────────────────────────────────┘
```

### Key Design Decision: No LLM for Intent Parsing

The existing English intent parser uses regex patterns — no external LLM call.
We follow the same pattern for Arabic: a **deterministic regex+dictionary
approach** for Egyptian Arabic intent parsing. This keeps:

- ✅ Zero latency overhead (no round-trip to LM Studio for parsing)
- ✅ Predictable behavior (no hallucination risk for price extraction)
- ✅ Testable with unit tests
- ✅ No dependency on LLM availability for basic chat functionality

The LLM (LM Studio) is only used for **product extraction from crawled pages**
(existing behavior, unchanged).

---

## Files Touched

| File | Action | Purpose |
|------|--------|---------|
| `services/chatbot/arabic_nlp.py` | **New** | Egyptian Arabic intent parser, language detection, number parsing, query translation dictionary |
| `services/chatbot/i18n.py` | **New** | Bot response templates in Arabic & English, locale-aware formatting |
| `services/chatbot/search_service.py` | **Modify** | Wire Arabic intent parsing into `parse_intent()`, add query translation |
| `services/chatbot/main.py` | **Modify** | Detect language, pass locale to response builder, localize bot messages |
| `services/chatbot/models.py` | **Modify** | Add `language` field to `ChatResponse` for the Flutter client to know directionality |
| `services/chatbot/test_arabic_nlp.py` | **New** | Unit tests for Arabic NLP module |
| `services/chatbot/test_search_service.py` | **Modify** | Add Arabic intent parsing tests |
| `services/chatbot/test_main.py` | **Modify** | Add Arabic message flow integration tests |

---

## Detailed Design

### 1. Language Detection (`arabic_nlp.py`)

A simple, fast heuristic — no ML model needed:

```python
import re
from typing import Optional

# Arabic Unicode ranges: U+0600–U+06FF (Arabic), U+0750–U+077F (supplement)
_ARABIC_CHAR_RE = re.compile(r'[\u0600-\u06FF\u0750-\u077F]')

def detect_language(text: str) -> str:
    """Detect if a message is Arabic or English.

    Returns 'ar' if ≥30% of alphabetic characters are Arabic, else 'en'.
    """
    arabic_count = len(_ARABIC_CHAR_RE.findall(text))
    total_alpha = sum(1 for c in text if c.isalpha())
    if total_alpha == 0:
        return 'en'
    return 'ar' if arabic_count / total_alpha >= 0.3 else 'en'
```

### 2. Arabic Intent Parser (`arabic_nlp.py`)

Handles Egyptian Arabic price keywords and number formats:

```python
def parse_arabic_intent(message: str) -> dict:
    """Parse Egyptian Arabic message into search query + price filter.

    Handles:
    - Price filters: أقل من, تحت, بحد أقصى, ميزانيتي, بسعر أقل من
    - Number words: ألف (1000), ألفين (2000), مية (100), نص (0.5×)
    - Eastern Arabic numerals: ١٢٣٤٥ → 12345
    - Comma-separated: 12,000 or ١٢٬٠٠٠
    - Combined forms: 12 ألف → 12000, خمستاشر ألف → 15000
    """
```

**Egyptian Arabic price filter patterns** (ordered by specificity):

| Pattern | Example | Extracted |
|---------|---------|-----------|
| `بسعر أقل من X` | بسعر أقل من 12 ألف | max_price=12000 |
| `أقل من X` | أقل من ٥٠٠٠ | max_price=5000 |
| `تحت X` | تحت 30000 | max_price=30000 |
| `بحد أقصى X` | بحد أقصى 15 ألف | max_price=15000 |
| `ميزانيتي X` | ميزانيتي 20 ألف | max_price=20000 |
| `مش أكتر من X` | مش أكتر من 10000 | max_price=10000 |
| `ب X جنيه` | ب 5000 جنيه | max_price=5000 |
| Trailing number | شاشات 2k ١٢٠٠٠ | max_price=12000 |

**Egyptian Arabic number parsing:**

| Input | Parsed |
|-------|--------|
| `12 ألف` | 12000 |
| `ألف` | 1000 |
| `ألفين` | 2000 |
| `خمستاشر ألف` | 15000 |
| `نص مليون` | 500000 |
| `١٢٬٠٠٠` | 12000 |
| `12,000` | 12000 |

### 3. Arabic → English Query Translation (`arabic_nlp.py`)

Most Egyptian e-commerce stores (Amazon, Noon, Jumia) accept English search
queries and return better results than Arabic queries. We need a lightweight
translation layer — **not a full machine translator**, but a focused
product-category dictionary.

```python
# Product category dictionary: Egyptian Arabic → English search term
PRODUCT_TRANSLATIONS = {
    # Electronics
    'شاشة': 'monitor',
    'شاشات': 'monitor',
    'لابتوب': 'laptop',
    'لاب توب': 'laptop',
    'كمبيوتر': 'computer',
    'موبايل': 'mobile phone',
    'تليفون': 'phone',
    'سماعات': 'headphones',
    'سماعة': 'headphone',
    'ماوس': 'mouse',
    'كيبورد': 'keyboard',
    'طابعة': 'printer',
    'راوتر': 'router',
    'هارد': 'hard drive',
    'فلاشة': 'flash drive',
    'شاحن': 'charger',
    'باور بانك': 'power bank',
    'كاميرا': 'camera',
    'تابلت': 'tablet',
    'تلفزيون': 'television',
    'تكييف': 'air conditioner',
    'ثلاجة': 'refrigerator',
    'غسالة': 'washing machine',
    # Gaming
    'بلايستيشن': 'playstation',
    'إكس بوكس': 'xbox',
    # Fashion
    'جزمة': 'shoes',
    'شنطة': 'bag',
    'تيشيرت': 't-shirt',
    'بنطلون': 'pants',
    # Appliances
    'خلاط': 'blender',
    'مكواة': 'iron',
    'ميكروويف': 'microwave',
    ...  # ~100 entries covering common Egyptian product categories
}

def translate_query_for_search(query: str) -> str:
    """Translate Arabic product terms to English for better store search.

    Preserves brand names, model numbers, and specs that are already
    Latin-script (e.g. '2k', 'RTX 4060', 'iPhone 15').

    Strategy:
    1. Split the query into tokens
    2. For each Arabic token, look up translation
    3. Preserve non-Arabic tokens as-is (brands, model numbers, specs)
    4. Join the result
    """
```

**Important**: Technical terms and brands that users naturally write in English
(or Arabizi) are preserved as-is: `2k`, `4K`, `RTX`, `Samsung`, `iPhone`,
`Lenovo`, etc. Only pure Arabic product-category words get translated.

### 4. Bot Response Localization (`i18n.py`)

A simple template system — no heavy i18n framework needed for the backend:

```python
MESSAGES = {
    'en': {
        'no_results': "I couldn't find any products matching '{query}'{price_filter}. Try a different search term.",
        'found_results': "I found {count} product{plural} matching '{query}'{price_filter}:",
        'added_to_feed': "I've added '{title}' to your tracking feed. I'll monitor the price and notify you when it changes.",
        'no_search_results': "No search results found to add to your feed.",
        'add_failed': "Sorry, I couldn't add this to your feed at the moment. Please try again later.",
        'insufficient_credits': "Insufficient credits: {detail}. Upgrade your plan to continue.",
        'empty_query': "Please enter a product to search for.",
        'price_filter': " under {max_price} EGP",
    },
    'ar': {
        'no_results': "مش لاقي منتجات لـ \"{query}\"{price_filter}. جرب كلمات تانية.",
        'found_results': "لقيت {count} منتج{plural} لـ \"{query}\"{price_filter}:",
        'added_to_feed': "تمام! أضفت \"{title}\" للمتابعة. هنبلغك لما السعر يتغير 👍",
        'no_search_results': "مفيش نتائج بحث لإضافتها.",
        'add_failed': "معلش، مقدرتش أضيف المنتج ده دلوقتي. جرب تاني بعدين.",
        'insufficient_credits': "رصيدك مش كفاية: {detail}. ممكن تطور باقتك.",
        'empty_query': "اكتب اسم المنتج اللي عايز تدور عليه.",
        'price_filter': " بأقل من {max_price} جنيه",
    },
}

def format_message(key: str, language: str = 'en', **kwargs) -> str:
    """Format a localized bot response message."""
    ...
```

> Note: The Arabic text uses **Egyptian dialect** (عامية مصرية), not Modern
> Standard Arabic (فصحى). This matches the user's input style and feels
> natural in a chat context. Examples: "مش لاقي" instead of "لم أجد",
> "هنبلغك" instead of "سنبلغك", "جرب تاني" instead of "حاول مرة أخرى".

### 5. Wiring Changes in `search_service.py`

Modify `parse_intent()` to be language-aware:

```python
from services.chatbot.arabic_nlp import (
    detect_language,
    parse_arabic_intent,
    translate_query_for_search,
)

def parse_intent(message: str) -> Dict[str, Any]:
    """Parse a user message into search query and optional price filter.

    Auto-detects Arabic vs English and uses the appropriate parser.
    """
    language = detect_language(message)

    if language == 'ar':
        result = parse_arabic_intent(message)
        # Translate Arabic product terms for store search URLs
        result['search_query'] = translate_query_for_search(result['query'])
        result['display_query'] = result['query']  # Keep Arabic for display
        result['language'] = 'ar'
    else:
        # Existing English parsing (unchanged)
        result = _parse_english_intent(message)
        result['search_query'] = result['query']
        result['display_query'] = result['query']
        result['language'] = 'en'

    return result
```

The `search()` method uses `search_query` (English) for store URLs, while the
bot response uses `display_query` (original Arabic) for user-facing messages.

### 6. Wiring Changes in `main.py`

The `send_message` endpoint gains language awareness:

```python
@app.post("/chatbot/message", response_model=ChatResponse)
async def send_message(...):
    # Parse intent (now language-aware)
    intent_result = await search_service.search_with_intent(chat_request.message)
    language = intent_result.get('language', 'en')
    display_query = intent_result['display_query']
    max_price = intent_result['max_price']
    results = intent_result['results']

    # Build bot response in the detected language
    if not results:
        bot_message = format_message(
            'no_results', language,
            query=display_query,
            price_filter=format_message('price_filter', language, max_price=max_price) if max_price else '',
        )
    else:
        count = len(results)
        bot_message = format_message(
            'found_results', language,
            count=count,
            plural='s' if language == 'en' and count > 1 else 'ات' if language == 'ar' and count > 2 else '',
            query=display_query,
            price_filter=...,
        )

    return ChatResponse(
        message=bot_message,
        session_id=session_id,
        search_results=search_results,
        language=language,  # New field
    )
```

### 7. Model Changes (`models.py`)

```python
class ChatResponse(BaseModel):
    """Response from the chatbot."""
    message: str
    session_id: UUID
    search_results: List[SearchResult] = Field(default_factory=list)
    language: str = "en"  # NEW: 'en' or 'ar' — Flutter uses this for RTL layout
```

### 8. Add-to-Feed via Arabic Commands

The chatbot should recognize Arabic commands to add items:

| Arabic Command | Meaning |
|---------------|---------|
| `أضف الأول` | Add the first result |
| `أضف رقم 2` | Add result #2 |
| `تابع ده` | Track this |
| `أضفه للمتابعة` | Add it to tracking |
| `عايز أتابع الأول` | I want to track the first |

This is handled in `arabic_nlp.py`:

```python
def parse_add_command(message: str) -> Optional[int]:
    """Parse an Arabic 'add to feed' command.

    Returns the 1-based result index, or None if not an add command.
    """
```

When the chatbot detects an add command, it triggers `_handle_add_to_feed()`
with the corresponding search result from the active session — no need for the
Flutter "Add to Feed" button (though the button still works).

### 9. Flutter Changes (Minimal)

The Flutter chat UI already:
- ✅ Supports Arabic locale (l10n files exist)
- ✅ Has RTL layout support (Flutter handles this automatically)
- ✅ Displays bot messages as-is (no hardcoded English in message display)

Only change needed:
- Read the `language` field from `ChatResponse` to adjust text direction
  in the message bubble (so Arabic messages render RTL even if the app locale
  is English).

```dart
// In ChatMessageBubble
TextDirection? _textDirection(ChatMessageModel msg) {
  // If the response indicates Arabic, force RTL for proper rendering
  return msg.language == 'ar' ? TextDirection.rtl : null;
}
```

---

## Test Strategy

### Unit Tests (`test_arabic_nlp.py`)

| Test Case | Input | Expected |
|-----------|-------|----------|
| Arabic detection | `عايز شاشات 2k` | `'ar'` |
| English detection | `gaming laptop under 50000` | `'en'` |
| Mixed (Arabic dominant) | `عايز laptop` | `'ar'` |
| Price: أقل من + ألف | `شاشات أقل من 12 ألف` | query=`شاشات`, max_price=`12000` |
| Price: تحت + number | `لابتوب تحت 30000` | query=`لابتوب`, max_price=`30000` |
| Price: بحد أقصى | `موبايل بحد أقصى ١٥٠٠٠` | query=`موبايل`, max_price=`15000` |
| Price: بسعر أقل من X ألف | `شاشات 2k بسعر أقل من 12 ألف` | query=`شاشات 2k`, max_price=`12000` |
| Price: مش أكتر من | `تابلت مش أكتر من عشر تلاف` | query=`تابلت`, max_price=`10000` |
| Eastern Arabic numerals | `شاشة ب ١٢٠٠٠ جنيه` | max_price=`12000` |
| Number word: ألفين | `سماعات أقل من ألفين` | max_price=`2000` |
| Query translation | `شاشات 2k` | `'monitor 2k'` |
| Preserve brands | `لابتوب Lenovo Legion` | `'laptop Lenovo Legion'` |
| Add command: أضف الأول | `أضف الأول` | index=`1` |
| Add command: أضف رقم 3 | `أضف رقم 3` | index=`3` |
| No add command | `شاشات 2k` | `None` |

### Integration Tests (`test_main.py` additions)

- Arabic message → Arabic bot response with search results
- Arabic add command → tracker created + Arabic confirmation
- Mixed session (Arabic search → English add command) works
- `ChatResponse.language` field is populated correctly

### Manual Smoke Test

```
1. Send: عايز شاشات 2k بسعر أقل من 12 ألف
   → Bot responds in Arabic with results, price filter applied

2. Send: أضف الأول
   → Bot confirms tracker created in Arabic

3. Verify the tracker appears in the Trackers tab

4. Send: gaming laptop under 50000
   → Bot responds in English (language auto-detected)

5. Send: عايز أرخص لابتوب
   → Bot searches for "laptop" across stores, responds in Arabic
```

---

## What This Plan Does NOT Include

- **Arabic store-side search** — Stores like Amazon Egypt and Noon already
  handle English queries well. Arabic search on these stores often returns
  worse results. If store Arabic search quality improves, we can add it later
  as a fallback.
- **Full NLP / LLM-based Arabic parsing** — The regex+dictionary approach
  covers 95%+ of Egyptian Arabic price queries. An LLM-based parser would add
  latency and complexity with minimal benefit for MVP.
- **Voice input** — Would require speech-to-text (whisper/Google STT).
  Interesting future feature but out of scope.
- **Arabic product names in results** — Search results come from stores in
  whatever language the store returns (usually English). Translating product
  titles back to Arabic would require another LLM call per result.

---

## Implementation Order

| Phase | Work | Estimate |
|-------|------|----------|
| **Phase 1** | `arabic_nlp.py`: language detection, Arabic intent parser, number parsing | Core |
| **Phase 2** | `arabic_nlp.py`: query translation dictionary, add-command parser | Core |
| **Phase 3** | `i18n.py`: bot response templates in Arabic & English | Core |
| **Phase 4** | Wire into `search_service.py` and `main.py` | Integration |
| **Phase 5** | `models.py`: add `language` field to `ChatResponse` | Small |
| **Phase 6** | Unit tests (`test_arabic_nlp.py`) + integration tests | Tests |
| **Phase 7** | Flutter: RTL text direction in chat bubbles | Small |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Arabic query translation misses a product category | Dictionary is easily extensible; log untranslated Arabic tokens for review |
| Eastern Arabic numeral edge cases | Comprehensive test suite; normalize early in the pipeline |
| Egyptian dialect variations (e.g., "حاجة" vs "منتج") | Include common synonyms in the parser |
| Store search returns 0 results for translated queries | Fall back to searching with the original Arabic query if English yields nothing |
| Mixed Arabic/English messages confuse the parser | Language detection uses character ratio, not word-level; handles mixed naturally |
