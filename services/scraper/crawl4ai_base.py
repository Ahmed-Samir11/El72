"""
Crawl4AI Base Scraper with Local LLM Integration.

This module provides a base class for scrapers that use Crawl4AI with
local LLM inference (via LM Studio) instead of hardcoded CSS selectors.

Key Features:
- LLM-based intelligent extraction (no brittle selectors)
- Local inference via LM Studio (OpenAI-compatible API)
- Robots.txt compliance with configurable strictness
- No paid API usage
- Async-first design
"""

import os
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urljoin, urlparse

# Crawl4AI imports
from crawl4ai import AsyncWebCrawler
from crawl4ai.extraction_strategy import LLMExtractionStrategy
from crawl4ai.chunking_strategy import RegexChunking

# OpenAI-compatible client for LM Studio
from openai import AsyncOpenAI

# Local imports
from extraction_schemas import (
    ProductPriceSchema, 
    SearchResultsSchema,
    SearchResultItem,
    PRODUCT_PAGE_EXTRACTION_PROMPT,
    SEARCH_RESULTS_EXTRACTION_PROMPT,
    StockStatus
)
from robots_handler import get_robots_handler, RobotsTxtMode

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

# LM Studio Configuration (OpenAI-compatible local endpoint)
LM_STUDIO_URL = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "local-model")  # LM Studio uses any model name

# Crawl4AI Configuration
CRAWL_TIMEOUT = int(os.getenv("CRAWL_TIMEOUT", "30"))
CRAWL_WAIT_FOR = os.getenv("CRAWL_WAIT_FOR", "networkidle")

# Extraction Configuration  
MAX_TOKENS_EXTRACTION = int(os.getenv("MAX_TOKENS_EXTRACTION", "2000"))


# =============================================================================
# LM Studio Client (Local LLM)
# =============================================================================

def get_lm_studio_client() -> AsyncOpenAI:
    """
    Get AsyncOpenAI client configured for LM Studio.
    
    LM Studio exposes an OpenAI-compatible API on localhost:1234.
    No API key needed for local inference.
    """
    return AsyncOpenAI(
        base_url=LM_STUDIO_URL,
        api_key="not-needed"  # LM Studio doesn't require a key
    )


class LMStudioExtractionStrategy(LLMExtractionStrategy):
    """
    Custom extraction strategy that uses LM Studio for local inference.
    
    Overrides the default LLM extraction to use our local LM Studio
    endpoint instead of OpenAI's paid API.
    """
    
    def __init__(
        self,
        schema: dict,
        extraction_prompt: str,
        model: str = None,
        **kwargs
    ):
        self.schema = schema
        self.extraction_prompt = extraction_prompt
        self.model = model or LM_STUDIO_MODEL
        self.client = get_lm_studio_client()
        super().__init__(**kwargs)
    
    async def extract(self, content: str, url: str = None) -> str:
        """
        Extract structured data from content using local LLM.
        
        Args:
            content: HTML or text content to extract from
            url: Source URL (for context)
            
        Returns:
            JSON string of extracted data
        """
        import json
        
        # Build the extraction prompt
        system_prompt = f"""{self.extraction_prompt}

Expected JSON schema:
{json.dumps(self.schema, indent=2)}

URL: {url or 'unknown'}
"""
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Extract product information from this page content:\n\n{content[:8000]}"}  # Truncate for context window
                ],
                max_tokens=MAX_TOKENS_EXTRACTION,
                temperature=0.1  # Low temperature for consistent extraction
            )
            
            result = response.choices[0].message.content
            
            # Try to parse as JSON to validate
            try:
                parsed = json.loads(result)
                return json.dumps(parsed)
            except json.JSONDecodeError:
                # Try to extract JSON from the response
                import re
                json_match = re.search(r'\{[\s\S]*\}', result)
                if json_match:
                    return json_match.group()
                logger.warning(f"Could not parse LLM response as JSON: {result[:200]}")
                return result
                
        except Exception as e:
            logger.error(f"LM Studio extraction failed: {e}")
            raise


# =============================================================================
# Crawl4AI Base Scraper
# =============================================================================

class Crawl4AIBaseScraper(ABC):
    """
    Base class for Crawl4AI-powered scrapers with local LLM extraction.
    
    Features:
    - Intelligent LLM-based extraction (no CSS selectors)
    - Local inference via LM Studio (no API costs)
    - Robots.txt compliance with configurable modes
    - Async-first design
    - Automatic crawl-delay handling
    
    Subclasses must implement:
    - store_id: Unique identifier for the store
    - store_name: Human-readable store name
    - base_url: Base URL for the store
    - get_search_url(): Build search URL for product queries
    """
    
    def __init__(self):
        self.robots_handler = get_robots_handler()
        self._crawler: Optional[AsyncWebCrawler] = None
        self._lm_client = get_lm_studio_client()
    
    # =========================================================================
    # Abstract Properties (Subclasses must implement)
    # =========================================================================
    
    @property
    @abstractmethod
    def store_id(self) -> str:
        """Unique identifier for the store (e.g., 'elbadrgroup', 'amazon_eg')."""
        pass
    
    @property
    @abstractmethod
    def store_name(self) -> str:
        """Human-readable store name (e.g., 'ElBadr Group', 'Amazon Egypt')."""
        pass
    
    @property
    @abstractmethod
    def base_url(self) -> str:
        """Base URL for the store (e.g., 'https://elbadrgroup.com')."""
        pass
    
    @abstractmethod
    def get_search_url(self, query: str) -> str:
        """
        Build the search URL for a product query.
        
        Args:
            query: Product search query
            
        Returns:
            Full search URL
        """
        pass
    
    # =========================================================================
    # Crawler Management
    # =========================================================================
    
    async def _get_crawler(self) -> AsyncWebCrawler:
        """Get or create the async web crawler instance."""
        if self._crawler is None:
            self._crawler = AsyncWebCrawler(
                headless=True,
                verbose=False
            )
            await self._crawler.__aenter__()
        return self._crawler
    
    async def close(self):
        """Close the crawler and release resources."""
        if self._crawler:
            await self._crawler.__aexit__(None, None, None)
            self._crawler = None
    
    # =========================================================================
    # Robots.txt Compliance
    # =========================================================================
    
    async def _check_robots_allowed(self, url: str) -> Tuple[bool, float]:
        """
        Check robots.txt compliance for a URL.
        
        Returns:
            Tuple of (is_allowed, crawl_delay)
        """
        is_allowed = await self.robots_handler.is_allowed(url)
        crawl_delay = await self.robots_handler.get_crawl_delay(url)
        return is_allowed, crawl_delay
    
    async def _respect_crawl_delay(self, url: str):
        """Wait for the crawl delay before making a request."""
        _, delay = await self._check_robots_allowed(url)
        if delay > 0:
            logger.debug(f"Respecting crawl-delay of {delay}s for {urlparse(url).netloc}")
            await asyncio.sleep(delay)
    
    # =========================================================================
    # Core Crawling Methods
    # =========================================================================
    
    async def crawl_page(self, url: str) -> Optional[str]:
        """
        Crawl a single page and return its content.
        
        Respects robots.txt based on configured mode.
        
        Args:
            url: URL to crawl
            
        Returns:
            Page content (HTML/text) or None if blocked/failed
        """
        # Check robots.txt
        is_allowed, crawl_delay = await self._check_robots_allowed(url)
        
        if not is_allowed:
            logger.warning(f"Blocked by robots.txt: {url}")
            return None
        
        # Respect crawl-delay
        if crawl_delay > 0:
            await asyncio.sleep(crawl_delay)
        
        try:
            crawler = await self._get_crawler()
            result = await crawler.arun(
                url=url,
                timeout=CRAWL_TIMEOUT * 1000,  # Convert to ms
                wait_for=CRAWL_WAIT_FOR
            )
            
            if result.success:
                return result.markdown or result.html
            else:
                logger.error(f"Crawl failed for {url}: {result.error_message}")
                return None
                
        except Exception as e:
            logger.error(f"Exception crawling {url}: {e}")
            return None
    
    async def extract_product_data(
        self, 
        url: str
    ) -> Optional[ProductPriceSchema]:
        """
        Extract product data from a product page URL.
        
        Uses LLM-based extraction via LM Studio.
        
        Args:
            url: Product page URL
            
        Returns:
            Extracted product data or None if failed
        """
        content = await self.crawl_page(url)
        if not content:
            return None
        
        try:
            strategy = LMStudioExtractionStrategy(
                schema=ProductPriceSchema.model_json_schema(),
                extraction_prompt=PRODUCT_PAGE_EXTRACTION_PROMPT
            )
            
            result_json = await strategy.extract(content, url)
            
            import json
            result_dict = json.loads(result_json)
            return ProductPriceSchema.model_validate(result_dict)
            
        except Exception as e:
            logger.error(f"Product extraction failed for {url}: {e}")
            return None
    
    async def extract_search_results(
        self, 
        query: str
    ) -> Optional[SearchResultsSchema]:
        """
        Search for products and extract results using LLM.
        
        Args:
            query: Product search query
            
        Returns:
            Extracted search results or None if failed
        """
        search_url = self.get_search_url(query)
        content = await self.crawl_page(search_url)
        
        if not content:
            return None
        
        try:
            strategy = LMStudioExtractionStrategy(
                schema=SearchResultsSchema.model_json_schema(),
                extraction_prompt=SEARCH_RESULTS_EXTRACTION_PROMPT
            )
            
            result_json = await strategy.extract(content, search_url)
            
            import json
            result_dict = json.loads(result_json)
            return SearchResultsSchema.model_validate(result_dict)
            
        except Exception as e:
            logger.error(f"Search extraction failed for {query}: {e}")
            return None
    
    # =========================================================================
    # High-Level API (Matches existing BaseScraper interface)
    # =========================================================================
    
    async def get_price(self, url: str) -> Optional[float]:
        """
        Get the price from a product page.
        
        Compatible with existing BaseScraper interface.
        
        Args:
            url: Product page URL
            
        Returns:
            Price as float or None if not found
        """
        product = await self.extract_product_data(url)
        return product.price if product else None
    
    async def search_product(
        self, 
        query: str
    ) -> Optional[Tuple[str, Optional[float]]]:
        """
        Search for a product and return best match.
        
        Compatible with existing BaseScraper interface.
        Uses token-based scoring to find best match.
        
        Args:
            query: Product search query
            
        Returns:
            Tuple of (product_url, price) or None if not found
        """
        results = await self.extract_search_results(query)
        if not results or not results.products:
            return None
        
        # Score and rank products
        best_match = self._find_best_match(query, results.products)
        if not best_match:
            return None
        
        # Resolve relative URLs
        product_url = best_match.url
        if not product_url.startswith('http'):
            product_url = urljoin(self.base_url, product_url)
        
        return (product_url, best_match.price)
    
    def _find_best_match(
        self, 
        query: str, 
        products: List[SearchResultItem]
    ) -> Optional[SearchResultItem]:
        """
        Find the best matching product from search results.
        
        Uses token overlap scoring similar to store_scrapers.py.
        
        Args:
            query: Original search query
            products: List of search result items
            
        Returns:
            Best matching product or None
        """
        if not products:
            return None
        
        query_lower = query.lower()
        query_tokens = set(query_lower.split())
        
        best_score = -1
        best_product = None
        
        for product in products:
            title_lower = product.title.lower()
            title_tokens = set(title_lower.split())
            
            # Token overlap score
            token_hits = len(query_tokens & title_tokens)
            
            # Length bonus (shorter titles often more relevant)
            length_bonus = 1.0 / (1 + len(title_lower) / 100)
            
            # Phrase bonus (exact phrase match)
            phrase_bonus = 1.0 if query_lower in title_lower else 0.0
            
            score = token_hits + length_bonus + phrase_bonus
            
            if score > best_score:
                best_score = score
                best_product = product
        
        return best_product
    
    async def scrape_product(
        self, 
        url: Optional[str] = None, 
        query: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Unified scraping method - either direct URL or search.
        
        Args:
            url: Direct product URL (optional)
            query: Search query (optional, used if no URL)
            
        Returns:
            Dict with price, title, stock_status, etc.
        """
        if url:
            product = await self.extract_product_data(url)
        elif query:
            search_result = await self.search_product(query)
            if not search_result:
                return {"error": "No products found", "store": self.store_id}
            product_url, _ = search_result
            product = await self.extract_product_data(product_url)
        else:
            return {"error": "No URL or query provided", "store": self.store_id}
        
        if not product:
            return {"error": "Failed to extract product data", "store": self.store_id}
        
        return {
            "store_id": self.store_id,
            "store_name": self.store_name,
            "title": product.title,
            "price": product.price,
            "original_price": product.original_price,
            "currency": product.currency.value,
            "stock_status": product.stock_status.value,
            "image_url": product.image_url,
            "sku": product.sku,
            "seller": product.seller,
            "rating": product.rating,
            "review_count": product.review_count
        }


# =============================================================================
# Context Manager Support
# =============================================================================

class Crawl4AIScraperContext:
    """Context manager for Crawl4AI scrapers."""
    
    def __init__(self, scraper: Crawl4AIBaseScraper):
        self.scraper = scraper
    
    async def __aenter__(self) -> Crawl4AIBaseScraper:
        return self.scraper
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.scraper.close()
