"""Structural tests for the hub-and-spoke documentation index.

These tests catch the silent-failure mode where an AI agent (or a
human) renames a spoke file without updating the navigation links
in the hub. The orchestrator would otherwise read a broken link,
fail to load the context, and proceed blind.

The check walks every markdown file in the hub-and-spoke system,
extracts the relative links, and asserts that each one resolves to
an existing file or directory on disk.

**Path convention.** All links in the docs are written as
repository-root-relative paths (e.g. ``.agent/context/hub.md``,
``backend/main.py``). This matches the working directory of the
AI agent's file tools and the Python orchestrator, so a link can
be pasted directly into a tool without path-manipulation.

**Optional docs.** Some docs (e.g. ``.agent/HANDOFF.md``) are
agent-maintained and safe to delete. The test treats them as
optional: when present, their links are validated; when absent,
the parametrized cases skip silently rather than failing the
build.

Run with: ``python -m pytest backend/tests/test_doc_links.py``
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repo root = three levels up from this file
# (backend/tests/test_doc_links.py -> backend/tests -> backend -> <root>).
REPO_ROOT = Path(__file__).resolve().parents[2]

# Required docs: must exist on disk. A missing required doc fails
# the build loudly so the orchestrator's navigation graph stays
# coherent.
REQUIRED_DOCS: tuple[Path, ...] = (
    REPO_ROOT / "README.md",
    REPO_ROOT / ".agent" / "README.md",
    REPO_ROOT / ".agent" / "AGENT.md",
    REPO_ROOT / ".agent" / "context" / "hub.md",
    REPO_ROOT / ".agent" / "context" / "VISION.md",
    REPO_ROOT / ".agent" / "context" / "ARCHITECTURE.md",
    REPO_ROOT / ".agent" / "context" / "LESSONS_LEARNED.md",
    # The contract docs are also part of the documentation surface
    # — they link to one another and to the source so they must
    # stay in sync.
    REPO_ROOT / ".agent" / "contracts" / "backend-module.md",
    REPO_ROOT / ".agent" / "contracts" / "frontend-module.md",
    REPO_ROOT / ".agent" / "contracts" / "settings-module.md",
)

# Optional docs: only included in the parametrised list when they
# actually exist on disk. Use this tier for hand-curated,
# agent-maintained files that are safe to delete.
OPTIONAL_DOCS: tuple[Path, ...] = (
    # Agent-maintained handoff log. Pass on the next agent's
    # working notebook: previous attempts, open work, observed
    # anti-patterns. Optional by design.
    REPO_ROOT / ".agent" / "HANDOFF.md",
)


def _docs_under_test() -> list[Path]:
    """Build the parametrised doc list.

    Required docs are always included so the existence checks
    fail loudly when one is missing. Optional docs are appended
    only when they actually exist on disk — a missing optional
    doc is silently skipped rather than a build failure.
    """
    docs: list[Path] = list(REQUIRED_DOCS)
    for optional in OPTIONAL_DOCS:
        if optional.exists():
            docs.append(optional)
    return docs


# Standard markdown link: [label](target). The label can contain
# anything; the target is the first parenthesised group. We keep
# the regex deliberately loose because the spoke docs use a mix
# of relative paths, anchor links, and backtick-wrapped links.
_MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

# Anything that starts with these schemes is an external link.
_EXTERNAL_SCHEMES = ("http://", "https://", "mailto:", "tel:")


def _strip_code_fences(text: str) -> str:
    """Remove fenced code blocks so we don't lint fake 'links' in
    ASCII tree diagrams (e.g. ``└── README.md``)."""
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def _extract_links(markdown_path: Path) -> list[str]:
    """Return the link targets found in ``markdown_path``.

    Strips inline code blocks, ignores empty targets and external
    URLs, and splits anchor fragments so the filesystem lookup runs
    against the resource path (not the ``#anchor``).
    """
    text = markdown_path.read_text(encoding="utf-8")
    text = _strip_code_fences(text)

    targets: list[str] = []
    for raw in _MARKDOWN_LINK.findall(text):
        # Markdown allows ``[label](target "title")``; strip the
        # optional title.
        target = raw.split(maxsplit=1)[0].strip()

        # Strip the anchor fragment before resolving.
        target = target.split("#", 1)[0]

        # Skip empties, pure anchors, and external links.
        if not target:
            continue
        if target.startswith(_EXTERNAL_SCHEMES):
            continue

        targets.append(target)

    return targets


@pytest.mark.parametrize("doc_path", _docs_under_test(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_doc_file_exists(doc_path: Path) -> None:
    """Every doc file under test must exist on disk.

    Required docs always appear in the parametrised list, so a
    missing required doc fails this test loudly. Optional docs
    are filtered out by ``_docs_under_test`` when they are absent.
    """
    in_required = doc_path in REQUIRED_DOCS
    assert doc_path.exists(), (
        f"Required document missing: {doc_path.relative_to(REPO_ROOT)}"
        if in_required
        else f"Document missing: {doc_path.relative_to(REPO_ROOT)}"
    )
    assert doc_path.is_file(), f"Document is not a file: {doc_path.relative_to(REPO_ROOT)}"


@pytest.mark.parametrize("doc_path", _docs_under_test(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_doc_links_resolve(doc_path: Path) -> None:
    """Every link in a hub/spoke doc must point to an existing
    file or directory.

    The docs use **repository-root-relative** paths, so each
    target is resolved from ``REPO_ROOT`` rather than from the
    doc's own directory. This matches the AI agent's working
    directory and makes links safe to copy-paste into a tool.

    This is the safety net for the "silent broken link" failure
    mode: a renamed or moved spoke file is caught by CI before
    the orchestrator tries to load it.
    """
    assert doc_path.exists(), (
        f"Cannot lint links in missing doc: {doc_path.relative_to(REPO_ROOT)}"
    )

    broken: list[str] = []
    for link in _extract_links(doc_path):
        # Resolve from the repo root (the AI agent's cwd).
        resolved = (REPO_ROOT / link).resolve()

        # Reject any link that escapes the repo (e.g. absolute
        # paths or stray ``../`` chains) so the test fails loudly
        # instead of asserting on someone else's filesystem.
        try:
            resolved.relative_to(REPO_ROOT)
        except ValueError:
            broken.append(f"{link} (escapes repo root → {resolved})")
            continue

        if not resolved.exists():
            broken.append(link)

    assert not broken, (
        f"Broken links in {doc_path.relative_to(REPO_ROOT)}:\n"
        + "\n".join(f"  - {link}" for link in broken)
    )


def test_no_relative_link_segments() -> None:
    """Hard guard against reintroducing relative paths
    (``../foo/bar`` or ``./foo``). The docs must use
    repository-root-relative paths so the AI orchestrator can
    paste them directly into a file tool.

    Only required docs are checked here: optional docs whose
    contents are agent-maintained (e.g. ``HANDOFF.md``) are
    not held to the same convention.
    """
    for doc_path in REQUIRED_DOCS:
        assert doc_path.exists(), (
            f"Cannot lint links in missing doc: {doc_path.relative_to(REPO_ROOT)}"
        )
        for link in _extract_links(doc_path):
            # ``..`` segments are the smoking gun — they only
            # make sense relative to the doc's directory, which
            # the AI agent does not know.
            assert "../" not in link and not link.startswith("./"), (
                f"{doc_path.relative_to(REPO_ROOT)} uses a relative "
                f"link '{link}'. Convert to a repository-root-relative "
                f"path (e.g. '.agent/context/hub.md')."
            )


def test_hub_has_no_legacy_link() -> None:
    """The hub must not reference the deleted legacy docs.

    Guards against a copy-paste regression that re-introduces
    ``AI_INSTRUCTIONS.md`` or ``archived_notes.md`` as live
    links. The "deleted" table entry is allowed because it is a
    plain string, not a markdown link.
    """
    hub_path = REPO_ROOT / ".agent" / "context" / "hub.md"
    assert hub_path.exists(), "hub.md is missing!"

    text = hub_path.read_text(encoding="utf-8")
    # Strip code blocks + tables so we only inspect actual links.
    text = _strip_code_fences(text)

    for raw in _MARKDOWN_LINK.findall(text):
        target = raw.split(maxsplit=1)[0].strip().split("#", 1)[0]
        if not target:
            continue
        assert "AI_INSTRUCTIONS" not in target, (
            f"hub.md links to deleted legacy doc: {target}"
        )
        assert "archived_notes" not in target, (
            f"hub.md links to deleted legacy doc: {target}"
        )


def test_hub_spokes_exist() -> None:
    """The four canonical spoke files must exist exactly where the
    hub says they do. This is a stricter superset of the link
    resolution test: it pins the contract names so a rename
    breaks the build immediately.
    """
    context_dir = REPO_ROOT / ".agent" / "context"
    for name in ("hub.md", "VISION.md", "ARCHITECTURE.md", "LESSONS_LEARNED.md"):
        assert (context_dir / name).is_file(), (
            f"Required spoke file missing: .agent/context/{name}"
        )


def test_optional_docs_filter() -> None:
    """The optional-doc filter correctly excludes missing
    files and includes existing ones.

    Sanity check on the helper so a future refactor cannot
    silently regress the optional-doc semantics.
    """
    docs = _docs_under_test()
    # All required docs are always present.
    for required in REQUIRED_DOCS:
        assert required in docs, (
            f"Required doc missing from _docs_under_test(): "
            f"{required.relative_to(REPO_ROOT)}"
        )
    # Optional docs are included only when they exist.
    for optional in OPTIONAL_DOCS:
        if optional.exists():
            assert optional in docs, (
                f"Existing optional doc missing from _docs_under_test(): "
                f"{optional.relative_to(REPO_ROOT)}"
            )
        else:
            assert optional not in docs, (
                f"Missing optional doc incorrectly included in _docs_under_test(): "
                f"{optional.relative_to(REPO_ROOT)}"
            )
