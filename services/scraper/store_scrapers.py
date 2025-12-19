"""Base scraper interface and store-specific implementations.

This module provides a clean abstraction for scraping different stores with
standardized output format.
"""

import asyncio
import hashlib
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Optional, Any
from playwright.async_api import Page, Error as PlaywrightError

logger = logging.getLogger(__name__)


class ScrapeResult:
    """Standardized scrape result across all stores."""
    
    def __init__(
        self,
        store: str,
        canonical_product_id: str,
        price: float,
        currency: str,
        in_stock: bool,
        url: str,
        timestamp: Optional[datetime] = None,
        title: Optional[str] = None,
        image_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.store = store
        self.canonical_product_id = canonical_product_id
        self.price = price
        self.currency = currency
        self.in_stock = in_stock
        self.url = url
        self.timestamp = timestamp or datetime.utcnow()
        self.title = title
        self.image_url = image_url
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "store": self.store,
            "canonical_product_id": self.canonical_product_id,
            "price": self.price,
            "currency": self.currency,
            "in_stock": self.in_stock,
            "url": self.url,
            "timestamp": self.timestamp.isoformat(),
            "title": self.title,
            "image_url": self.image_url,
            "metadata": self.metadata
        }


class BaseScraper(ABC):
    """Abstract base class for store scrapers.
    
    Each store implementation must:
    1. Implement extract_price, extract_stock_status, extract_title
    2. Define store_id class attribute
    3. Handle store-specific rate limits
    """
    
    store_id: str = "base"
    
    def __init__(self, rate_limit_delay: float = 1.0):
        """Initialize scraper with rate limiting.
        
        Args:
            rate_limit_delay: Minimum seconds between requests to this store
        """
        self.rate_limit_delay = rate_limit_delay
        self._last_request_time = 0.0
        
    async def _enforce_rate_limit(self):
        """Enforce rate limiting between requests."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = asyncio.get_event_loop().time()
    
    @abstractmethod
    async def extract_price(self, page: Page) -> Optional[float]:
        """Extract price from the page.
        
        Returns:
            Price as float or None if not found
        """
        pass
    
    @abstractmethod
    async def extract_stock_status(self, page: Page) -> bool:
        """Check if product is in stock.
        
        Returns:
            True if in stock, False otherwise
        """
        pass
    
    async def extract_title(self, page: Page) -> Optional[str]:
        """Extract product title (optional, implemented by subclasses)."""
        return None
    
    async def extract_image_url(self, page: Page) -> Optional[str]:
        """Extract product image URL (optional)."""
        return None
    
    async def search_product(self, page: Page, product_name: str) -> Optional[str]:
        """Search for a product and return the product page URL.
        
        Args:
            page: Playwright page instance
            product_name: Product name/query to search
            
        Returns:
            Product URL or None if not found
        """
        # Default implementation; stores should override
        return None
    
    def parse_price_text(self, text: str) -> Optional[float]:
        """Generic price parsing utility.
        
        Handles formats like:
        - EGP 1,200.00
        - 1,200.00 EGP
        - $99.99
        - 99.99
        """
        if not text:
            return None
        # Strip currency symbols and letters
        cleaned = re.sub(r"[^\d,\.]", "", text)
        if not cleaned:
            return None
        # Remove thousands separators
        cleaned = cleaned.replace(",", "")
        try:
            return float(cleaned)
        except ValueError:
            return None
    
    async def scrape(
        self,
        page: Page,
        url: str,
        canonical_product_id: str
    ) -> Optional[ScrapeResult]:
        """Execute scraping for a product URL.
        
        Args:
            page: Playwright page instance
            url: Product URL to scrape (or product name to search for)
            canonical_product_id: Unified product identifier
            
        Returns:
            ScrapeResult or None if scraping failed
        """
        await self._enforce_rate_limit()
        
        try:
            # If url looks like a search query (no http/https), perform search
            actual_url = url
            if not url.startswith("http"):
                search_result = await self.search_product(page, url)
                if not search_result:
                    logger.warning(f"Could not find product '{url}' on {self.store_id}")
                    return None
                actual_url = search_result
                logger.info(f"Found product on {self.store_id}: {actual_url}")
            
            # Navigate to URL with timeout
            await page.goto(actual_url, timeout=20000)
            
            # Extract data
            price = await self.extract_price(page)
            in_stock = await self.extract_stock_status(page)
            title = await self.extract_title(page)
            image_url = await self.extract_image_url(page)
            
            if price is None:
                logger.warning(f"Failed to extract price from {actual_url}")
                return None
            
            return ScrapeResult(
                store=self.store_id,
                canonical_product_id=canonical_product_id,
                price=price,
                currency=self.get_default_currency(),
                in_stock=in_stock,
                url=actual_url,
                title=title,
                image_url=image_url
            )
            
        except PlaywrightError as e:
            logger.error(f"Playwright error scraping {url}: {e}")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error scraping {url}: {e}")
            return None
    
    @abstractmethod
    def get_default_currency(self) -> str:
        """Return the default currency for this store (e.g., 'EGP', 'USD')."""
        pass


class AmazonEgyptScraper(BaseScraper):
    """Scraper for Amazon Egypt (amazon.eg)."""
    
    store_id = "amazon_eg"
    
    def __init__(self):
        super().__init__(rate_limit_delay=2.0)  # Conservative rate limit
    
    async def extract_price(self, page: Page) -> Optional[float]:
        """Extract price using Amazon's selectors."""
        selectors = [
            "span.a-price.aok-align-center span.a-offscreen",
            "#priceblock_ourprice",
            "#priceblock_dealprice",
            "span.a-price span.a-offscreen",
            ".a-price .a-offscreen"
        ]
        
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    price = self.parse_price_text(text)
                    if price:
                        return price
            except Exception:
                continue
        
        return None
    
    async def extract_stock_status(self, page: Page) -> bool:
        """Check stock status on Amazon."""
        out_of_stock_indicators = [
            "#availability span.a-color-price",
            "#availability span.a-color-state",
            "text='Currently unavailable'",
            "text='Out of stock'"
        ]
        
        for selector in out_of_stock_indicators:
            try:
                element = await page.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    if any(phrase in text.lower() for phrase in ["unavailable", "out of stock", "currently out"]):
                        return False
            except Exception:
                continue
        
        return True
    
    async def extract_title(self, page: Page) -> Optional[str]:
        """Extract product title."""
        selectors = ["#productTitle", "#title", "span#productTitle"]
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    return (await element.inner_text()).strip()
            except Exception:
                continue
        return None
    
    async def extract_image_url(self, page: Page) -> Optional[str]:
        """Extract main product image."""
        try:
            element = await page.query_selector("#landingImage")
            if element:
                return await element.get_attribute("src")
        except Exception:
            pass
        return None
    
    async def search_product(self, page: Page, product_name: str) -> Optional[str]:
        """Search for a product on Amazon Egypt and return first result URL."""
        try:
            search_url = f"https://www.amazon.eg/s?k={'+'.join(product_name.split())}"
            await page.goto(search_url, timeout=20000)
            await page.wait_for_timeout(2000)  # Wait for JS to load
            
            # Amazon uses .s-asin for result items with product links
            first_result = await page.query_selector(".s-asin a[href*='/dp/']")
            if first_result:
                href = await first_result.get_attribute("href")
                if href:
                    # Make absolute URL and clean params
                    if href.startswith("/"):
                        href = f"https://www.amazon.eg{href}"
                    # Extract clean URL without tracking params
                    if "?" in href:
                        href = href.split("?")[0]
                    return href
        except Exception as e:
            logger.warning(f"Amazon Egypt search failed for '{product_name}': {e}")
        return None
    
    def get_default_currency(self) -> str:
        return "EGP"


class NoonScraper(BaseScraper):
    """Scraper for Noon.com (Egypt and UAE)."""
    
    store_id = "noon"
    
    def __init__(self):
        super().__init__(rate_limit_delay=1.5)
    
    async def extract_price(self, page: Page) -> Optional[float]:
        """Extract price from Noon."""
        selectors = [
            "div.priceNow",
            "span.sellingPrice",
            "[data-qa='product-price']"
        ]
        
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    price = self.parse_price_text(text)
                    if price:
                        return price
            except Exception:
                continue
        
        return None
    
    async def extract_stock_status(self, page: Page) -> bool:
        """Check if product is in stock on Noon."""
        try:
            # Look for "Out of Stock" or similar messages
            out_of_stock = await page.query_selector("text=/out of stock/i")
            if out_of_stock:
                return False
            
            # Check for "Add to Cart" button presence (indicates in stock)
            add_to_cart = await page.query_selector("button[data-qa='add-to-cart']")
            return add_to_cart is not None
        except Exception:
            return True  # Default to in stock if check fails
    
    async def extract_title(self, page: Page) -> Optional[str]:
        """Extract product title from Noon."""
        selectors = ["h1.productTitle", "[data-qa='product-name']"]
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    return (await element.inner_text()).strip()
            except Exception:
                continue
        return None
    
    async def search_product(self, page: Page, product_name: str) -> Optional[str]:
        """Search for a product on Noon and return first result URL."""
        try:
            search_url = f"https://www.noon.com/egypt-en/search?q={'+'.join(product_name.split())}"
            await page.goto(search_url, timeout=20000)
            await page.wait_for_timeout(2000)  # Wait for JS to load results
            
            # Noon uses a[href*='/p/'] for product links in search results
            first_result = await page.query_selector("a[href*='/p/']")
            if first_result:
                href = await first_result.get_attribute("href")
                if href:
                    # Make absolute URL
                    if href.startswith("/"):
                        return f"https://www.noon.com{href}"
                    return href
        except Exception as e:
            logger.warning(f"Noon search failed for '{product_name}': {e}")
        return None
    
    def get_default_currency(self) -> str:
        return "EGP"  # Default, but should be detected from page


class JumiaScraper(BaseScraper):
    """Scraper for Jumia Egypt."""
    
    store_id = "jumia"
    
    def __init__(self):
        super().__init__(rate_limit_delay=1.5)
    
    async def extract_price(self, page: Page) -> Optional[float]:
        """Extract price from Jumia."""
        selectors = [
            "span.-tal",  # Jumia's price class
            "[data-qa='product-price']",
            ".prc"
        ]
        
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    price = self.parse_price_text(text)
                    if price:
                        return price
            except Exception:
                continue
        
        return None
    
    async def extract_stock_status(self, page: Page) -> bool:
        """Check stock status on Jumia."""
        try:
            # Look for out of stock indicators
            out_of_stock = await page.query_selector("text=/out of stock/i")
            if out_of_stock:
                return False
            
            # Check for add to cart button
            add_to_cart = await page.query_selector("button.add")
            return add_to_cart is not None
        except Exception:
            return True
    
    async def extract_title(self, page: Page) -> Optional[str]:
        """Extract product title."""
        selectors = ["h1.-fs20", "h1.title"]
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    return (await element.inner_text()).strip()
            except Exception:
                continue
        return None
    
    def get_default_currency(self) -> str:
        return "EGP"
    
    async def search_product(self, page: Page, product_name: str) -> Optional[str]:
        """Search for a product on Jumia and return first result URL."""
        try:
            search_url = f"https://www.jumia.com.eg/catalog/?q={'+'.join(product_name.split())}"
            await page.goto(search_url, timeout=20000)
            await page.wait_for_timeout(2000)  # Wait for JS to load results
            
            # Jumia uses a[href*='/p/'] for product links in search results
            first_result = await page.query_selector("a[href*='/p/']")
            if first_result:
                href = await first_result.get_attribute("href")
                if href:
                    # Make absolute URL
                    if href.startswith("/"):
                        return f"https://www.jumia.com.eg{href}"
                    return href
        except Exception as e:
            logger.warning(f"Jumia search failed for '{product_name}': {e}")
        return None


class ScraperFactory:
    """Factory for creating store-specific scrapers."""
    
    _scrapers = {
        "amazon_eg": AmazonEgyptScraper,
        "noon": NoonScraper,
        "jumia": JumiaScraper,
    }
    
    @classmethod
    def get_scraper(cls, store_id: str) -> Optional[BaseScraper]:
        """Get scraper instance for a store.
        
        Args:
            store_id: Store identifier (e.g., 'amazon_eg')
            
        Returns:
            Scraper instance or None if store not supported
        """
        scraper_class = cls._scrapers.get(store_id)
        if scraper_class:
            return scraper_class()
        logger.warning(f"No scraper found for store: {store_id}")
        return None
    
    @classmethod
    def register_scraper(cls, store_id: str, scraper_class: type):
        """Register a new scraper for a store.
        
        Args:
            store_id: Store identifier
            scraper_class: Scraper class (must inherit from BaseScraper)
        """
        if not issubclass(scraper_class, BaseScraper):
            raise ValueError("Scraper class must inherit from BaseScraper")
        cls._scrapers[store_id] = scraper_class
        logger.info(f"Registered scraper for store: {store_id}")
    
    @classmethod
    def list_supported_stores(cls) -> list:
        """Get list of supported store IDs."""
        return list(cls._scrapers.keys())


class ElBadrGroupScraper(BaseScraper):
    """Scraper for El Badr Group Egypt (elbadrgroupeg.store)."""

    store_id = "elbadrgroup"

    def __init__(self):
        # Conservative delay; adjust if their robots/policies require longer
        super().__init__(rate_limit_delay=1.5)

    async def extract_price(self, page: Page) -> Optional[float]:
        """Extract price trying common Shopify-like selectors and fallbacks."""
        # Try meta price first (often present on Shopify themes)
        try:
            meta_price = await page.query_selector("meta[itemprop='price']")
            if meta_price:
                content = await meta_price.get_attribute("content")
                if content:
                    p = self.parse_price_text(content)
                    if p is not None:
                        return p
        except Exception:
            pass

        selectors = [
            # ElBadrGroup specific (Journal3 theme)
            "div.product-price",
            # Also try in the price group wrapper
            ".product-price-group .product-price",
            # Common Shopify theme selectors
            "span.price-item.price-item--regular",
            "div.price__regular .price-item--regular",
            ".price .price-item",
            "span.money",
            "[data-product-price]",
            # Generic fallbacks
            "span.price",
            ".product__price .price",
            "#price",
        ]

        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    price = self.parse_price_text(text)
                    if price is not None:
                        return price
            except Exception:
                continue
        return None

    async def extract_stock_status(self, page: Page) -> bool:
        """Check stock status using common patterns and button states."""
        # Explicit out-of-stock phrases
        try:
            oos = await page.query_selector("text=/sold out|out of stock/i")
            if oos:
                return False
        except Exception:
            pass

        # Button disabled state (Shopify forms)
        try:
            # Add to cart buttons commonly named 'add' or have product-form__submit
            btn = await page.query_selector("button[name='add'], .product-form__submit")
            if btn:
                disabled = await btn.get_attribute("disabled")
                if disabled is not None:
                    return False
                # If button text says sold out
                try:
                    txt = (await btn.inner_text() or "").lower()
                    if "sold out" in txt or "out of stock" in txt:
                        return False
                except Exception:
                    pass
        except Exception:
            pass

        # If no explicit OOS indicators found, assume in stock
        return True

    async def extract_title(self, page: Page) -> Optional[str]:
        selectors = [
            "h1.product__title",
            "h1.product-title",
            "h1[itemprop='name']",
            "h1",
        ]
        for selector in selectors:
            try:
                el = await page.query_selector(selector)
                if el:
                    return (await el.inner_text()).strip()
            except Exception:
                continue
        return None

    def get_default_currency(self) -> str:
        return "EGP"
    
    async def search_product(self, page: Page, product_name: str) -> Optional[str]:
        """Search for a product on ElBadrGroup and return the best matching result URL."""
        try:
            # Use the correct search URL format for ElBadrGroup
            search_url = f"https://elbadrgroupeg.store/index.php?route=product/search&search={'+'.join(product_name.split())}"
            await page.goto(search_url, timeout=20000)
            await page.wait_for_timeout(2000)  # Wait for JS to load results

            # Gather all product links then pick the best text match rather than the first one
            links = await page.query_selector_all(".name a[href]")
            if links:
                target_tokens = [t for t in product_name.lower().split() if t]

                def score(text: str, href: str) -> float:
                    t = text.lower()
                    h = (href or "").lower()
                    # Score by overlap of provided tokens in either text or URL
                    token_hits = sum(1 for tok in target_tokens if tok in t or tok in h)
                    # Favor longer token matches (e.g., model strings) to reduce false positives
                    length_bonus = sum(len(tok) for tok in target_tokens if tok in t or tok in h) / 50.0
                    # Small bonus if the full product name (or most of it) appears as a substring
                    phrase = " ".join(target_tokens)
                    phrase_bonus = 1 if phrase and phrase in t else 0
                    return token_hits + length_bonus + phrase_bonus

                best_link = None
                best_score = -1
                for link in links:
                    text = (await link.inner_text() or "")
                    href = await link.get_attribute("href")
                    s = score(text, href or "")
                    if s > best_score:
                        best_score = s
                        best_link = link

                if best_link:
                    href = await best_link.get_attribute("href")
                    if href:
                        if href.startswith("/"):
                            return f"https://elbadrgroupeg.store{href}"
                        return href
        except Exception as e:
            logger.warning(f"ElBadrGroup search failed for '{product_name}': {e}")
        return None


# Register El Badr Group scraper in the factory
ScraperFactory.register_scraper("elbadrgroup", ElBadrGroupScraper)
