"""Compatibility shim for the robots.txt handler.

The implementation moved to `services/common/robots.py` so the scraper and
the chatbot share one robots.txt contract (cross-service imports are
forbidden; `services/common/` is the shared library).

This module stays for two reasons:

* the scraper containers import it flat (`from robots_handler import
  get_robots_handler` in `crawl4ai_base.py`), and
* existing tests patch `services.scraper.robots_handler.httpx.AsyncClient`;
  `httpx` is re-exported below so that patch target still resolves to the
  same module object the shared implementation uses.
"""

import httpx  # re-export: patch target for existing scraper tests

from services.common.robots import (
    RobotsCache,
    RobotsTxtHandler,
    RobotsTxtMode,
    check_robots_allowed,
    get_crawl_delay,
    get_robots_handler,
)

__all__ = [
    "httpx",
    "RobotsCache",
    "RobotsTxtHandler",
    "RobotsTxtMode",
    "check_robots_allowed",
    "get_crawl_delay",
    "get_robots_handler",
]
