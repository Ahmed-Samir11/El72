"""Test setup for the chatbot service.

``robotexclusionrulesparser`` is a runtime dependency of the shared robots.txt
contract (``services/common/robots.py``) that the chatbot uses. CI installs it
from ``requirements-test.txt``; where it is absent, register a minimal stub so
the chatbot unit tests stay collectable — the parser's own behaviour is covered
by ``services/scraper/test_robots_handler.py``, and the stub warns so a missing
runtime dependency cannot hide behind it.
"""

import sys
import warnings
from types import ModuleType

import pytest


def _ensure_robots_parser() -> None:
    """Make ``robotexclusionrulesparser`` importable for these tests.

    The real package wins when installed, and an already-registered stub from
    another suite is left alone: ``services/common/robots.py`` binds whichever
    module is imported first, so the stand-in mirrors the semantics of
    ``services/scraper/test_robots_handler.py``'s stub (including its ``_allowed``
    flag) instead of inventing a second, conflicting one.
    """
    try:  # pragma: no cover - the real package is used whenever installed
        import robotexclusionrulesparser  # noqa: F401
    except ImportError:
        pass

    if "robotexclusionrulesparser" in sys.modules:
        return

    class _FakeParser:
        """Stand-in for RobotExclusionRulesParser: allows everything."""

        def __init__(self):
            self._allowed = True
            self.content = ""

        def parse(self, content):
            self.content = content or ""

        def is_allowed(self, user_agent, url):
            return self._allowed

    _stub = ModuleType("robotexclusionrulesparser")
    _stub.RobotExclusionRulesParser = _FakeParser
    sys.modules["robotexclusionrulesparser"] = _stub
    # Loud on purpose: a stub that allows every path could mask a missing
    # runtime dependency in the image. services/chatbot/test_deployment_layout.py
    # asserts the real distribution is declared in the service requirements.
    warnings.warn(
        "robotexclusionrulesparser is not installed; chatbot robots.txt tests "
        "run against a permissive stub.",
        stacklevel=2,
    )


_ensure_robots_parser()


class PermissiveRobotsPolicy:
    """A robots policy that never blocks a crawl and never delays one.

    Unit tests must not fetch ``robots.txt`` from the internet; the shared
    handler's real behaviour is tested where it lives, not here.
    """

    def __init__(self):
        self.checked: list = []

    async def is_allowed(self, url: str) -> bool:
        """Allow [url] and record that the check happened."""
        self.checked.append(url)
        return True

    async def get_declared_crawl_delay(self, url: str):
        """No site asked for a delay."""
        return None


@pytest.fixture
def permissive_robots():
    """Return a [PermissiveRobotsPolicy] for tests that build a search service."""
    return PermissiveRobotsPolicy()
