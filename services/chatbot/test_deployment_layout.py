"""Guards for the chatbot container layout (flat modules + shared library).

The image is not a checkout: ``services/chatbot/*.py`` are copied flat into
``/app`` and the shared library goes to ``/app/common``, so ``common.auth`` is
importable there while ``services.common.auth`` is not. Every module therefore
carries a fallback import, and every dependency has to be listed in
requirements.txt because the image installs nothing else.

These tests read the Dockerfile, the modules and the requirements file rather
than building an image, so they run in the normal ``pytest services`` job.
"""

import ast
import re
import sys
from pathlib import Path

CHATBOT_DIR = Path(__file__).resolve().parent
SERVICES_DIR = CHATBOT_DIR.parent
COMMON_DIR = SERVICES_DIR / "common"
DOCKERFILE = (CHATBOT_DIR / "Dockerfile").read_text(encoding="utf-8")
REQUIREMENTS = (CHATBOT_DIR / "requirements.txt").read_text(encoding="utf-8")

# Modules the service imports at startup, in the order main.py pulls them in.
SERVICE_MODULES = [
    "main",
    "search_service",
    "models",
    "arabic_nlp",
    "i18n",
    "cache",
    "extractors",
    "store_health",
]
# Shared-library modules the chatbot depends on (JWT + robots.txt contracts).
SHARED_MODULES = ["auth", "robots"]

# Import name -> distribution name, for the ones that differ.
PACKAGES = {
    "jose": "python-jose",
    "PIL": "pillow",
    "cv2": "opencv-python",
    "dateutil": "python-dateutil",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _absolute_imports(tree: ast.Module):
    """Yield every absolute import name in [tree], module or package."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            yield node.module


def _local_module_names() -> set:
    """Module names importable flat, i.e. what the image layout provides."""
    names = {
        path.stem
        for path in CHATBOT_DIR.glob("*.py")
        if not path.name.startswith("test_")
    }
    names.add("common")
    names.update(f"common.{path.stem}" for path in COMMON_DIR.glob("*.py"))
    return names


def _requirement_names() -> set:
    names = set()
    for line in REQUIREMENTS.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.add(re.split(r"[<>=!\[\s;]", line)[0])
    return names


def test_the_image_copies_every_service_module():
    """A module added to the service must also be copied, or the container
    starts and dies on ImportError."""
    copied = {
        path.name
        for path in (
            CHATBOT_DIR / name
            for name in re.findall(r"services/chatbot/([A-Za-z0-9_]+\.py)", DOCKERFILE)
        )
    }
    expected = {f"{name}.py" for name in SERVICE_MODULES}
    assert expected <= copied, f"Dockerfile does not copy: {sorted(expected - copied)}"

    on_disk = {
        path.name
        for path in CHATBOT_DIR.glob("*.py")
        if not path.name.startswith("test_")
        and path.name not in {"conftest.py", "__init__.py"}
    }
    # __init__.py is checkout-only: the image has no services/chatbot package,
    # it loads these modules flat, so there is nothing for a package init to do.
    assert (
        on_disk <= copied
    ), f"service modules missing from the Dockerfile: {sorted(on_disk - copied)}"


def test_the_shared_library_lands_where_the_service_looks_for_it():
    """``services/common/`` must be copied to ``/app/common``.

    The chatbot is copied flat, so its package root is ``/app``: the shared
    library is importable as ``common.*`` there, which is what the fallback
    branch of every shared import uses.
    """
    assert re.search(
        r"^COPY\s+services/common/\s+/app/common/", DOCKERFILE, re.MULTILINE
    ), "the shared library is not copied to /app/common"
    assert "COPY services/chatbot/" in DOCKERFILE or re.search(
        r"COPY services/chatbot/[^\n]+ \./", DOCKERFILE
    ), "the service itself is not copied into /app"


def test_service_imports_resolve_in_the_container_layout():
    """Every absolute import must resolve inside the image.

    A ``services.chatbot.*`` import only works in a checkout, so each one must
    be paired with the flat fallback the image can actually load; a third-party
    import must be installed by requirements.txt.
    """
    local = _local_module_names()
    requirements = _requirement_names()

    for name in SERVICE_MODULES:
        tree = _tree(CHATBOT_DIR / f"{name}.py")
        imports = set(_absolute_imports(tree))

        prefixed = {i for i in imports if i.startswith("services.chatbot.")}
        flat = {i for i in imports if i in local or i.split(".")[0] in local}

        for import_name in prefixed:
            fallback = import_name.split(".", 2)[2]
            assert fallback in flat, (
                f"{name}.py imports {import_name} with no flat "
                f"({fallback}) fallback for the container layout"
            )

        for import_name in imports:
            root = import_name.split(".")[0]
            if root in local or root in {"services", "test_"}:
                continue
            if root in sys.stdlib_module_names:
                continue
            distribution = PACKAGES.get(root, root).lower()
            assert distribution in {r.lower() for r in requirements}, (
                f"{name}.py imports {root}, which requirements.txt does not " "install"
            )


def test_the_shared_library_is_paired_with_the_fallback_import():
    """``services.common.*`` must always have a ``common.*`` partner.

    This is the exact import the review flagged: the image has no ``services``
    package, so an unpaired shared import breaks the container at startup.
    """
    for name in SERVICE_MODULES:
        imports = set(_absolute_imports(_tree(CHATBOT_DIR / f"{name}.py")))
        shared = {i for i in imports if i.startswith("services.common.")}
        for import_name in shared:
            partner = import_name[len("services.") :]
            assert partner in imports, f"{name}.py cannot import {partner} in the image"


def test_the_shared_library_dependencies_are_installed():
    """The image must carry what ``common.auth`` and ``common.robots`` need.

    ``robotexclusionrulesparser`` is imported by the shared robots handler, not
    by the chatbot itself, so it is easy to forget in the service requirements;
    the chatbot conftest stubs that parser when it is missing, which would
    otherwise hide the gap from CI.
    """
    requirements = {r.lower() for r in _requirement_names()}

    for name in SHARED_MODULES:
        path = COMMON_DIR / f"{name}.py"
        assert path.exists(), f"shared module {name} is gone"
        for import_name in _absolute_imports(_tree(path)):
            root = import_name.split(".")[0]
            if root in sys.stdlib_module_names or root in {"services", "common"}:
                continue
            distribution = PACKAGES.get(root, root).lower()
            assert distribution in requirements, (
                f"common/{name}.py imports {root}; add it to "
                "services/chatbot/requirements.txt"
            )
