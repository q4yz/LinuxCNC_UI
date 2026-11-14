#!/usr/bin/env python3
"""docs/ (Sphinx + MyST Markdown) -> a GitHub wiki (plain Markdown).

    python3 scripts/docs_to_wiki.py <wiki-checkout> [--commit <sha>]

The wiki is flat, so every page becomes ``<Title-With-Dashes>.md`` (its
first ``# `` heading); ``docs/index.md`` becomes ``Home.md``, its toctrees
the sidebar (``_Sidebar.md``) and the section lists on Home. Converted:

* ``{doc}`path``` / ``{doc}`text <path>``` -> ``[Title](Page-Name)``
* ``:::{admonition} Title`` boxes -> a ``> **Title**`` quote
* definition lists (``Term`` / ``: text``) -> ``**Term** — text``
* ``../images/x.png`` -> the image on the repository's main branch

Every page the wiki had that docs/ no longer has is removed: docs/ is the
source, the wiki a generated copy (``_Footer.md`` says so).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = "q4yz/LinuxCNC_UI"
DOCS = Path(__file__).resolve().parents[1] / "docs"
IMAGE_BASE = f"https://github.com/{REPO}/raw/main/images/"

_TOCTREE = re.compile(r"```\{toctree\}\n(.*?)```", re.S)
_DOC_ROLE = re.compile(r"\{doc\}`(?:([^`<]+?)\s*<([^`>]+)>|([^`]+))`")
_ADMONITION = re.compile(r"^:::\{admonition\}[ \t]*(.*?)\n(.*?)^:::[ \t]*$", re.S | re.M)
_IMAGE = re.compile(r"\]\((?:\.\./)+images/([^)]+)\)")


def title_of(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ").capitalize()


def wiki_name(title: str) -> str:
    """A wiki page's file name (without .md) for a title."""
    name = re.sub(r"[^\w\s.-]", "", title).strip()
    return re.sub(r"\s+", "-", name)


def collect() -> dict[str, tuple[str, str]]:
    """docname ("getting-started/config") -> (title, wiki page name)."""
    pages: dict[str, tuple[str, str]] = {}
    for path in sorted(DOCS.rglob("*.md")):
        if "_build" in path.parts:
            continue
        doc = path.relative_to(DOCS).with_suffix("").as_posix()
        title = title_of(path)
        pages[doc] = (title, "Home" if doc == "index" else wiki_name(title))
    names = [name for _, name in pages.values()]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        sys.exit(f"two pages map to the same wiki page: {sorted(duplicates)}")
    return pages


def toctrees(index_text: str) -> list[tuple[str, list[str]]]:
    """(caption, [docname, ...]) per toctree of index.md."""
    sections = []
    for body in _TOCTREE.findall(index_text):
        caption = ""
        docs = []
        for line in body.splitlines():
            line = line.strip()
            if line.startswith(":caption:"):
                caption = line.split(":", 2)[2].strip()
            elif line and not line.startswith(":"):
                docs.append(line)
        sections.append((caption, docs))
    return sections


def convert(text: str, doc: str, pages: dict[str, tuple[str, str]]) -> str:
    base = Path(doc).parent

    def link(match: re.Match) -> str:
        label, target = (match.group(1), match.group(2)) if match.group(2) else (None, match.group(3))
        resolved = Path(base, target.strip()).as_posix()
        parts: list[str] = []
        for part in resolved.split("/"):
            if part == "..":
                if parts:
                    parts.pop()
            elif part not in ("", "."):
                parts.append(part)
        key = "/".join(parts)
        if key not in pages:
            sys.exit(f"{doc}: link to unknown page {target!r}")
        title, name = pages[key]
        return f"[{label or title}]({name})"

    def admonition(match: re.Match) -> str:
        body = [l for l in match.group(2).splitlines() if not l.startswith(":class:")]
        return "\n".join([f"> **{match.group(1).strip()}**", ">", *[f"> {l}".rstrip() for l in body]])

    # ``code`` spans (an example of the syntax itself) stay as they are
    spans: list[str] = []

    def mask(match: re.Match) -> str:
        spans.append(match.group(0))
        return f"\x00{len(spans) - 1}\x00"

    text = re.sub(r"``.+?``", mask, text)
    text = _DOC_ROLE.sub(link, text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)
    text = _ADMONITION.sub(admonition, text)
    text = _IMAGE.sub(lambda m: f"]({IMAGE_BASE}{m.group(1)})", text)

    # definition lists: "Term\n: text\n  more" -> "**Term** — text more"
    out: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(": ") and out and out[-1].strip():
            term = out.pop()
            definition = [line[2:].strip()]
            while i + 1 < len(lines) and lines[i + 1].startswith("  ") and lines[i + 1].strip():
                i += 1
                definition.append(lines[i].strip())
            out.append(f"**{term.strip()}** — {' '.join(definition)}")
        else:
            out.append(line)
        i += 1
    return "\n".join(out).rstrip() + "\n"


def build(wiki: Path, commit: str | None) -> list[str]:
    pages = collect()
    index_text = (DOCS / "index.md").read_text(encoding="utf-8")
    sections = toctrees(index_text)
    written: list[str] = []

    def write(name: str, text: str) -> None:
        (wiki / f"{name}.md").write_text(text, encoding="utf-8")
        written.append(f"{name}.md")

    for doc, (_, name) in pages.items():
        if doc == "index":
            continue
        write(name, convert((DOCS / f"{doc}.md").read_text(encoding="utf-8"), doc, pages))

    # Home: the index's text without its toctrees, then the sections as lists
    home = _TOCTREE.sub("", index_text)
    home = re.sub(r"\n{3,}", "\n\n", home).rstrip() + "\n"
    lists = []
    for caption, docs in sections:
        lists.append(f"\n## {caption}\n")
        lists.extend(f"- [{pages[d][0]}]({pages[d][1]})" for d in docs)
    write("Home", convert(home + "\n".join(lists), "index", pages))

    sidebar = ["**[Home](Home)**"]
    for caption, docs in sections:
        sidebar.append(f"\n**{caption}**\n")
        sidebar.extend(f"- [{pages[d][0]}]({pages[d][1]})" for d in docs)
    write("_Sidebar", "\n".join(sidebar) + "\n")

    source = f"https://github.com/{REPO}/tree/main/docs"
    at = f" at commit [`{commit[:7]}`](https://github.com/{REPO}/commit/{commit})" if commit else ""
    write("_Footer", f"Generated from [`docs/`]({source}){at} — edit the pages there, not here: "
                     "changes made in the wiki are overwritten.\n")

    for stale in wiki.glob("*.md"):
        if stale.name not in written:
            stale.unlink()
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("wiki", type=Path, help="a checkout of the wiki repository")
    parser.add_argument("--commit", help="the docs' commit, named in the footer")
    args = parser.parse_args()
    if not (args.wiki / ".git").exists():
        parser.error(f"{args.wiki} is not a git checkout")
    for name in build(args.wiki, args.commit):
        print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
