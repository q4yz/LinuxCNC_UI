# Sphinx configuration for the LinuxCNC Web UI documentation.
#
# Built like the Remora docs (remora-docs.readthedocs.io): Sphinx + the
# Read the Docs theme, hosted by Read the Docs (.readthedocs.yaml at the
# repo root), one version per branch / tag ("latest" = the default
# branch). Pages are Markdown (MyST); reStructuredText works as well.
#
# Build locally:
#   pip install -r docs/requirements.txt
#   sphinx-build -b html docs docs/_build/html

project = "LinuxCNC Web UI"
author = "q4yz"
copyright = "2026, q4yz"

extensions = [
    "myst_parser",
    "sphinx.ext.autosectionlabel",
]

# Markdown and reStructuredText pages
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
myst_enable_extensions = ["colon_fence", "deflist", "tasklist"]
myst_heading_anchors = 3
# "page:Section" labels, unique across pages
autosectionlabel_prefix_document = True

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "requirements.txt"]

html_theme = "sphinx_rtd_theme"
html_title = "LinuxCNC Web UI"
html_theme_options = {
    "navigation_depth": 3,
    "collapse_navigation": False,
    "sticky_navigation": True,
    "style_external_links": True,
}
# "Edit on GitHub" at the top of every page
html_context = {
    "display_github": True,
    "github_user": "q4yz",
    "github_repo": "LinuxCNC_UI",
    "github_version": "main",
    "conf_py_path": "/docs/",
}
