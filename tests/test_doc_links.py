"""Guard documentation links and prompt references against deleted files."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"\]\(([^)\s]+)\)")
PROMPT = re.compile(r"\.github/prompts/([\w.-]+\.md)")


def _doc_files():
    yield ROOT / "README.md"
    yield ROOT / "AGENTS.md"
    yield from sorted((ROOT / "docs").rglob("*.md"))


def test_relative_markdown_links_resolve():
    missing = []
    for doc in _doc_files():
        text = re.sub(r"```.*?```", "", doc.read_text(encoding="utf-8"), flags=re.S)
        for target in LINK.findall(text):
            if re.match(r"[a-z]+:", target) or target.startswith("#"):
                continue
            path = target.split("#", 1)[0]
            if path and not (doc.parent / path).exists():
                missing.append(f"{doc.relative_to(ROOT)} -> {target}")
    assert not missing, "\n".join(missing)


def test_no_missing_prompt_references():
    missing = []
    for top in ("src", "tests"):
        for src in (ROOT / top).rglob("*.py"):
            for name in PROMPT.findall(src.read_text(encoding="utf-8")):
                if not (ROOT / ".github" / "prompts" / name).exists():
                    missing.append(f"{src.relative_to(ROOT)}: {name}")
    assert not missing, "\n".join(missing)
