"""Robots.txt handler with configurable strictness modes.

This module provides ethical crawling support by respecting robots.txt directives
with three configurable modes:
- STRICT: Fully respect all directives (Disallow + Crawl-Delay)
- SOFT: Honor Crawl-Delay but ignore Disallow paths
- LOG_ONLY: Log violations but don't block any requests

Usage:
    handler = RobotsTxtHandler(mode=RobotsTxtMode.SOFT)
    
    # Check if URL is allowed
    if await handler.is_allowed("https://amazon.eg/product/123"):
        # Proceed with scraping
        delay = await handler.get_crawl_delay("https://amazon.eg")
        await asyncio.sleep(delay)
        # ... scrape
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Optional
from urllib.parse import urlparse

import httpx
from robotexclusionrulesparser import RobotExclusionRulesParser

logger = logging.getLogger(__name__)


class RobotsTxtMode(Enum):
    """Robots.txt compliance modes."""
    
    STRICT = "strict"      # Fully respect: skip disallowed paths + honor Crawl-Delay
    SOFT = "soft"          # Soft respect: honor Crawl-Delay but ignore Disallow
    LOG_ONLY = "log_only"  # Log-only: log violations but don't block


@dataclass
class RobotsCache:
    """Cached robots.txt data for a domain."""
    
    parser: RobotExclusionRulesParser
    fetched_at: datetime
    crawl_delay: float
    sitemap_urls: list


class RobotsTxtHandler:
    """Handler for robots.txt with configurable strictness.
    
    Attributes:
        mode: Compliance mode (STRICT, SOFT, LOG_ONLY)
        user_agent: User-Agent string to identify as
        cache_ttl: How long to cache robots.txt (default: 1 hour)
        default_delay: Default delay if no Crawl-Delay specified
    """
    
    DEFAULT_USER_AGENT = "ElhaqBot/1.0 (+https://elhaq.app/bot)"
    DEFAULT_CACHE_TTL = timedelta(hours=1)
    DEFAULT_DELAY = 1.0  # 1 second between requests
    
    def __init__(
        self,
        mode: RobotsTxtMode = None,
        user_agent: str = None,
        cache_ttl: timedelta = None,
        default_delay: float = None,
    ):
        # Load mode from env or use default
        mode_str = os.getenv("ROBOTS_TXT_MODE", "soft").lower()
        self.mode = mode or RobotsTxtMode(mode_str)
        
        self.user_agent = user_agent or os.getenv(
            "SCRAPER_USER_AGENT", self.DEFAULT_USER_AGENT
        )
        self.cache_ttl = cache_ttl or self.DEFAULT_CACHE_TTL
        self.default_delay = default_delay or float(
            os.getenv("SCRAPER_DEFAULT_DELAY", str(self.DEFAULT_DELAY))
        )
        
        # Cache: domain -> RobotsCache
        self._cache: Dict[str, RobotsCache] = {}
        self._lock = asyncio.Lock()
        
        logger.info(
            f"RobotsTxtHandler initialized: mode={self.mode.value}, "
            f"user_agent={self.user_agent}"
        )
    
    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
    
    async def _fetch_robots_txt(self, domain: str) -> Optional[str]:
        """Fetch robots.txt content from a domain."""
        robots_url = f"{domain}/robots.txt"
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    robots_url,
                    headers={"User-Agent": self.user_agent},
                    follow_redirects=True,
                )
                
                if response.status_code == 200:
                    logger.debug(f"Fetched robots.txt from {domain}")
                    return response.text
                elif response.status_code == 404:
                    logger.debug(f"No robots.txt at {domain} (404)")
                    return None
                else:
                    logger.warning(
                        f"Unexpected status {response.status_code} for {robots_url}"
                    )
                    return None
                    
        except Exception as e:
            logger.warning(f"Failed to fetch robots.txt from {domain}: {e}")
            return None
    
    def _parse_robots_txt(self, content: str) -> RobotsCache:
        """Parse robots.txt content into a RobotsCache."""
        parser = RobotExclusionRulesParser()
        parser.parse(content)
        
        # Extract Crawl-Delay for our user agent
        crawl_delay = self.default_delay
        
        # Try to get crawl delay from content
        for line in content.split('\n'):
            line = line.strip().lower()
            if line.startswith('crawl-delay:'):
                try:
                    delay_str = line.split(':', 1)[1].strip()
                    crawl_delay = float(delay_str)
                    logger.debug(f"Found Crawl-Delay: {crawl_delay}")
                except (ValueError, IndexError):
                    pass
        
        # Extract sitemap URLs
        sitemap_urls = []
        for line in content.split('\n'):
            line = line.strip()
            if line.lower().startswith('sitemap:'):
                sitemap_url = line.split(':', 1)[1].strip()
                sitemap_urls.append(sitemap_url)
        
        return RobotsCache(
            parser=parser,
            fetched_at=datetime.utcnow(),
            crawl_delay=crawl_delay,
            sitemap_urls=sitemap_urls,
        )
    
    async def _get_cache(self, url: str) -> RobotsCache:
        """Get or fetch robots.txt cache for a URL's domain."""
        domain = self._get_domain(url)
        
        async with self._lock:
            # Check if cached and not expired
            if domain in self._cache:
                cache = self._cache[domain]
                age = datetime.utcnow() - cache.fetched_at
                if age < self.cache_ttl:
                    return cache
            
            # Fetch fresh robots.txt
            content = await self._fetch_robots_txt(domain)
            
            if content:
                cache = self._parse_robots_txt(content)
            else:
                # No robots.txt - create permissive cache
                parser = RobotExclusionRulesParser()
                parser.parse("")  # Empty = allow all
                cache = RobotsCache(
                    parser=parser,
                    fetched_at=datetime.utcnow(),
                    crawl_delay=self.default_delay,
                    sitemap_urls=[],
                )
            
            self._cache[domain] = cache
            return cache
    
    async def is_allowed(self, url: str) -> bool:
        """Check if scraping this URL is allowed.
        
        Behavior depends on mode:
        - STRICT: Return False if Disallow matches
        - SOFT: Always return True (ignore Disallow)
        - LOG_ONLY: Log if disallowed but return True
        
        Args:
            url: The URL to check
            
        Returns:
            True if allowed to scrape, False otherwise
        """
        cache = await self._get_cache(url)
        is_allowed = cache.parser.is_allowed(self.user_agent, url)
        
        if self.mode == RobotsTxtMode.STRICT:
            if not is_allowed:
                logger.info(f"[STRICT] Blocked by robots.txt: {url}")
            return is_allowed
            
        elif self.mode == RobotsTxtMode.SOFT:
            if not is_allowed:
                logger.debug(f"[SOFT] Would be blocked (ignored): {url}")
            return True  # Ignore Disallow
            
        elif self.mode == RobotsTxtMode.LOG_ONLY:
            if not is_allowed:
                logger.warning(f"[LOG_ONLY] Violating robots.txt: {url}")
            return True  # Log but allow
        
        return True
    
    async def get_crawl_delay(self, url: str) -> float:
        """Get the Crawl-Delay for a URL's domain.
        
        Always respected regardless of mode (ethical minimum).
        
        Args:
            url: Any URL from the domain
            
        Returns:
            Delay in seconds between requests
        """
        cache = await self._get_cache(url)
        return cache.crawl_delay
    
    async def get_sitemaps(self, url: str) -> list:
        """Get sitemap URLs from robots.txt.
        
        Args:
            url: Any URL from the domain
            
        Returns:
            List of sitemap URLs
        """
        cache = await self._get_cache(url)
        return cache.sitemap_urls
    
    def clear_cache(self):
        """Clear the robots.txt cache."""
        self._cache.clear()
        logger.debug("Robots.txt cache cleared")


# Global singleton instance
_handler: Optional[RobotsTxtHandler] = None


def get_robots_handler() -> RobotsTxtHandler:
    """Get the global RobotsTxtHandler instance."""
    global _handler
    if _handler is None:
        _handler = RobotsTxtHandler()
    return _handler


async def check_robots_allowed(url: str) -> bool:
    """Convenience function to check if URL is allowed."""
    return await get_robots_handler().is_allowed(url)


async def get_crawl_delay(url: str) -> float:
    """Convenience function to get crawl delay for a domain."""
    return await get_robots_handler().get_crawl_delay(url)
