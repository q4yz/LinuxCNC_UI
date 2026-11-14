# Writing these docs

The pages are Markdown files (MyST) in `docs/`, built with
[Sphinx](https://www.sphinx-doc.org) and the Read the Docs theme. Read the Docs builds and
hosts them: one version per branch and tag, *latest* is the default branch.

## Build locally

```bash
python3 -m venv .venv-docs
.venv-docs/bin/pip install -r docs/requirements.txt
.venv-docs/bin/sphinx-build -b html -W --keep-going docs docs/_build/html
```

Open `docs/_build/html/index.html`. `-W` turns warnings (a broken link, a page missing from
every toctree) into errors, as CI and Read the Docs do.

## Add a page

1. Create `docs/<section>/<page>.md` starting with a `# Title`.
2. Add it to the section's `toctree` in `docs/index.md`.
3. Link other pages with `` {doc}`../section/page` ``.

## Hosting

- **Read the Docs** — import the repository once on readthedocs.org; `.readthedocs.yaml` at
  the repository root says how to build. Activate the versions (branches, tags) to publish.
- **CI** builds the docs on every push and pull request (the *docs* job), so a broken page
  fails before it reaches Read the Docs.
