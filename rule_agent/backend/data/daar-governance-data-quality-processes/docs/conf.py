# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.

import os
import sys


def log(message) -> None:
    print(f"### sphinx - {message}")


# TODO: improve getting PROJECT_ROOT_DIR and PROJECT_VERSION (not that elegant but at least works)
# this configuration file will be copied (in generate_docs.sh) to: $PROJECT_ROOT_DIR/docs/source
# (yes, this is a little bit "hacky")
PROJECT_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, PROJECT_ROOT_DIR)
sys.path.insert(0, f"{PROJECT_ROOT_DIR}/scripts")

from scripts.get_project_version import get_project_version  # noqa

log(f'Added dir to PYTHONPATH for "autodoc": {PROJECT_ROOT_DIR}')


# -- Project information -----------------------------------------------------


project = "Data Mesh Data Quality Application"
copyright = "2023, CCHBC"  # pylint: disable=redefined-builtin
author = "CCHBC"
release = version = get_project_version()

log(f"Generating project documentation for: {project} {version}")

# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
]
templates_path = ["_templates"]
exclude_patterns = ["_build"]
add_module_names = False
autodoc_member_order = "groupwise"

# -- Options for HTML output -------------------------------------------------

html_theme = "nature"
html_theme_options = {
    "body_max_width": "none",
}
html_static_path = ["_static"]
