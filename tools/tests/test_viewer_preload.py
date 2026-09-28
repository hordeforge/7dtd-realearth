"""The viewer's modulepreload list must match its real module graph.

viewer/index.html preloads the entry module's static imports so the graph
downloads in parallel. A stale entry there costs a request round trip (a
404) or, worse, lets a dynamic import back onto the first-paint path: the
Globe module drags in 1.3 MB of vendored three.js.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[2] / "viewer" / "src"
ENTRY = "app"
# js/<name>.js for every module scripts/build-viewer.sh emits.
PRELOADED_SUFFIX = ".js"
IMPORT_RE = re.compile(r'from\s+"\./([A-Za-z0-9_]+)\.js"')
LINE_COMMENT_RE = re.compile(r"//[^\n]*")


def strip_comments(source: str) -> str:
    """Drop // comments so an import statement is not glued to the prose above it."""
    return LINE_COMMENT_RE.sub("", source)


class PreloadCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "link":
            return
        rel = dict(attrs).get("rel")
        href = dict(attrs).get("href")
        if rel == "modulepreload" and href is not None:
            self.hrefs.append(href)


def value_imports(module: str) -> set[str]:
    """Modules `module` imports at runtime; `import type` is erased at build."""
    source = strip_comments((SRC_DIR / f"{module}.ts").read_text(encoding="utf-8"))
    found: set[str] = set()
    for statement in source.split(";"):
        stripped = statement.lstrip()
        if not stripped.startswith("import") or stripped.startswith("import type"):
            continue
        found.update(IMPORT_RE.findall(statement))
    return found


def reachable_from(entry: str) -> set[str]:
    seen: set[str] = set()
    pending = [entry]
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        pending.extend(value_imports(module) - seen)
    return seen


@pytest.fixture(scope="module")
def preloaded() -> set[str]:
    parser = PreloadCollector()
    parser.feed((SRC_DIR.parent / "index.html").read_text(encoding="utf-8"))
    return {href for href in parser.hrefs if href.startswith("js/")}


def test_preload_covers_exactly_the_static_module_graph(preloaded: set[str]):
    assert preloaded == {f"js/{name}{PRELOADED_SUFFIX}" for name in reachable_from(ENTRY)}


def test_lazy_globe_is_not_preloaded(preloaded: set[str]):
    assert "js/globe.js" not in preloaded
