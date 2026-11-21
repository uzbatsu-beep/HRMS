#!/usr/bin/env python3
"""Check repository-local Markdown links, without network access."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".venv", "venv", "node_modules", "dist", ".pytest_cache"}
LINK = re.compile(r"!?\[[^\]\n]*\]\((?P<dest>[^)\n]+)\)")
FENCE = re.compile(r"^\s*(\x60{3,}|~{3,})")


def links_from_markdown(text: str) -> list[str]:
    """Find inline destinations outside fenced code; external URLs remain unchecked."""
    inside = False
    marker = ""
    found: list[str] = []
    for line in text.splitlines():
        fence = FENCE.match(line)
        if fence:
            symbol = fence.group(1)[0]
            if not inside:
                inside, marker = True, symbol
            elif symbol == marker:
                inside, marker = False, ""
            continue
        if inside:
            continue
        for match in LINK.finditer(line):
            raw = match.group("dest").strip()
            if raw.startswith("<") and ">" in raw:
                raw = raw[1:raw.index(">")]
            else:
                raw = raw.split(' "', 1)[0].split(" '", 1)[0]
            found.append(raw)
    return found


def relative_target(source: Path, link: str) -> Path | None:
    """Return an absolute repository file path or None for external/anchor-only."""
    if not link or link.startswith("#") or link.startswith("//"):
        return None
    parsed = urlsplit(link)
    if parsed.scheme or parsed.netloc:
        return None
    path = unquote(parsed.path)
    if not path:
        return None
    candidate = ROOT / path.lstrip("/") if path.startswith("/") else source.parent / path
    return candidate.resolve()


def run() -> int:
    issues: list[str] = []
    docs = 0
    links = 0
    for source in sorted(ROOT.rglob("*.md")):
        if any(item in EXCLUDED for item in source.relative_to(ROOT).parts):
            continue
        docs += 1
        for dest in links_from_markdown(source.read_text(encoding="utf-8")):
            target = relative_target(source, dest)
            if target is None:
                continue
            links += 1
            if not target.is_relative_to(ROOT):
                issues.append(f"{source.relative_to(ROOT)}: outside repo: {dest}")
            elif not target.exists():
                issues.append(f"{source.relative_to(ROOT)}: missing {dest}")
    print(f"Markdown integrity: {docs} files, {links} local links, {len(issues)} errors")
    for issue in issues:
        print("ERROR:", issue, file=sys.stderr)
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(run())
