"""
Crawl4AI Store Implementations.

These scrapers use Crawl4AI with local LLM inference (LM Studio)
for intelligent extraction instead of hardcoded CSS selectors.

Benefits over CSS selectors:
- Resilient to site layout changes
- No selector maintenance
- Works with any e-commerce site structure
- No paid API costs (local LLM)
"""

from typing import Optional
from urllib.parse import quote_plus

from crawl4ai_base import Crawl4AIBaseScraper


# =============================================================================
# ElBadr Group (Crawl4AI)
# =============================================================================

class ElBadrGroupCrawl4AI(Crawl4AIBaseScraper):
    """
    ElBadr Group scraper using Crawl4AI + local LLM extraction.
    
    Site: https://elbadrgroup.com
    Categories: Computer hardware, GPUs, CPUs, peripherals
    """
    
    @property
    def store_id(self) -> str:
        return "elbadrgroup"
    
    @property
    def store_name(self) -> str:
        return "ElBadr Group"
    
    @property
    def base_url(self) -> str:
        return "https://elbadrgroup.com"
    
    def get_search_url(self, query: str) -> str:
        """Build ElBadr search URL."""
        encoded_query = quote_plus(query)
        return f"{self.base_url}/index.php?route=product/search&search={encoded_query}"


# =============================================================================
# Amazon Egypt (Crawl4AI)
# =============================================================================

class AmazonEgyptCrawl4AI(Crawl4AIBaseScraper):
    """
    Amazon Egypt scraper using Crawl4AI + local LLM extraction.
    
    Site: https://www.amazon.eg
    Categories: Everything (marketplace)
    """
    
    @property
    def store_id(self) -> str:
        return "amazon_eg"
    
    @property
    def store_name(self) -> str:
        return "Amazon Egypt"
    
    @property
    def base_url(self) -> str:
        return "https://www.amazon.eg"
    
    def get_search_url(self, query: str) -> str:
        """Build Amazon Egypt search URL."""
        encoded_query = quote_plus(query)
        return f"{self.base_url}/s?k={encoded_query}"


# =============================================================================
# 2B Egypt (Crawl4AI)
# =============================================================================

class TwoBEgyptCrawl4AI(Crawl4AIBaseScraper):
    """
    2B Egypt scraper using Crawl4AI + local LLM extraction.
    
    Site: https://www.2b.com.eg
    Categories: Computer hardware, laptops, accessories
    """
    
    @property
    def store_id(self) -> str:
        return "2b_egypt"
    
    @property
    def store_name(self) -> str:
        return "2B Egypt"
    
    @property
    def base_url(self) -> str:
        return "https://www.2b.com.eg"
    
    def get_search_url(self, query: str) -> str:
        """Build 2B Egypt search URL."""
        encoded_query = quote_plus(query)
        return f"{self.base_url}/search?q={encoded_query}"


# =============================================================================
# Sigma Computer (Crawl4AI)
# =============================================================================

class SigmaComputerCrawl4AI(Crawl4AIBaseScraper):
    """
    Sigma Computer scraper using Crawl4AI + local LLM extraction.
    
    Site: https://www.sigma-computer.com
    Categories: Computer hardware, GPUs, CPUs, gaming
    """
    
    @property
    def store_id(self) -> str:
        return "sigma_computer"
    
    @property
    def store_name(self) -> str:
        return "Sigma Computer"
    
    @property
    def base_url(self) -> str:
        return "https://www.sigma-computer.com"
    
    def get_search_url(self, query: str) -> str:
        """Build Sigma Computer search URL."""
        encoded_query = quote_plus(query)
        return f"{self.base_url}/en/search?s={encoded_query}"


# =============================================================================
# EgyPrice (Crawl4AI)
# =============================================================================

class EgyPriceCrawl4AI(Crawl4AIBaseScraper):
    """
    EgyPrice scraper using Crawl4AI + local LLM extraction.
    
    Site: https://egyprice.com
    Categories: Price comparison aggregator
    """
    
    @property
    def store_id(self) -> str:
        return "egyprice"
    
    @property
    def store_name(self) -> str:
        return "EgyPrice"
    
    @property
    def base_url(self) -> str:
        return "https://egyprice.com"
    
    def get_search_url(self, query: str) -> str:
        """Build EgyPrice search URL."""
        encoded_query = quote_plus(query)
        return f"{self.base_url}/search?q={encoded_query}"


# =============================================================================
# Factory Function
# =============================================================================

CRAWL4AI_SCRAPERS = {
    "elbadrgroup": ElBadrGroupCrawl4AI,
    "amazon_eg": AmazonEgyptCrawl4AI,
    "2b_egypt": TwoBEgyptCrawl4AI,
    "sigma_computer": SigmaComputerCrawl4AI,
    "egyprice": EgyPriceCrawl4AI,
}


def get_crawl4ai_scraper(store_id: str) -> Optional[Crawl4AIBaseScraper]:
    """
    Get a Crawl4AI scraper instance by store ID.
    
    Args:
        store_id: Store identifier
        
    Returns:
        Scraper instance or None if not found
    """
    scraper_class = CRAWL4AI_SCRAPERS.get(store_id)
    if scraper_class:
        return scraper_class()
    return None


def get_all_crawl4ai_store_ids() -> list:
    """Get list of all available Crawl4AI store IDs."""
    return list(CRAWL4AI_SCRAPERS.keys())


# =============================================================================
# CLI Test Runner
# =============================================================================

async def test_scraper(store_id: str, query: str = None, url: str = None):
    """
    Test a Crawl4AI scraper.
    
    Args:
        store_id: Store to test
        query: Search query (optional)
        url: Direct product URL (optional)
    """
    import json
    
    scraper = get_crawl4ai_scraper(store_id)
    if not scraper:
        print(f"Unknown store: {store_id}")
        print(f"Available stores: {get_all_crawl4ai_store_ids()}")
        return
    
    print(f"\n{'='*60}")
    print(f"Testing: {scraper.store_name} ({scraper.store_id})")
    print(f"Base URL: {scraper.base_url}")
    print(f"{'='*60}")
    
    try:
        result = await scraper.scrape_product(url=url, query=query)
        print(f"\nResult:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        await scraper.close()


if __name__ == "__main__":
    import argparse
    import asyncio
    
    parser = argparse.ArgumentParser(description="Test Crawl4AI scrapers")
    parser.add_argument("--store", required=True, help="Store ID to test")
    parser.add_argument("--query", help="Search query")
    parser.add_argument("--url", help="Direct product URL")
    
    args = parser.parse_args()
    
    if not args.query and not args.url:
        print("Error: Provide either --query or --url")
        exit(1)
    
    asyncio.run(test_scraper(args.store, query=args.query, url=args.url))
