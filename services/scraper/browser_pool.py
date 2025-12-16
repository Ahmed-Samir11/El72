import asyncio
from typing import List, Optional


class BrowserPool:
    """A simple async pool of launched Playwright browser instances.

    Usage:
        pool = BrowserPool(playwright, max_browsers=2)
        await pool.start()
        browser = await pool.acquire()
        try:
            # use browser
        finally:
            await pool.release(browser)
        await pool.close()
    """

    def __init__(
        self, playwright, max_browsers: int = 2, browser_type: str = "chromium"
    ):
        self._playwright = playwright
        self._max = max_browsers
        self._browser_type = browser_type
        self._browsers: List = []
        self._queue: Optional[asyncio.Queue] = None

    async def start(self) -> None:
        """Launch `max_browsers` browser instances and populate the pool."""
        self._queue = asyncio.Queue(maxsize=self._max)
        for _ in range(self._max):
            browser = await getattr(self._playwright, self._browser_type).launch(
                headless=True
            )
            self._browsers.append(browser)
            await self._queue.put(browser)

    async def acquire(self):
        """Acquire a browser instance from the pool (awaitable)."""
        if self._queue is None:
            raise RuntimeError("BrowserPool not started")
        return await self._queue.get()

    async def release(self, browser) -> None:
        """Return a browser instance back to the pool."""
        if self._queue is None:
            return
        await self._queue.put(browser)

    async def close(self) -> None:
        """Close all browser instances cleanly."""
        # clear queue to avoid blocking
        if self._queue is not None:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except Exception:
                    break
        for b in self._browsers:
            try:
                await b.close()
            except Exception:
                pass
        self._browsers = []
        self._queue = None
