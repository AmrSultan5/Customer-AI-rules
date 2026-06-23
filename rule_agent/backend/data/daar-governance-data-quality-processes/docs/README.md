# How to generate the project documentation?

## Prerequisites
1. Install `sphinx` using pip: `pip install --upgrade sphinx`

## Procedure
1. Open terminal and go to the project root directory
1. Run this script from the project root directory: `bash scripts/generate_docs.sh`
1. The project documentation will be exported as html files
1. Open with your web browser: `docs/source/_build/html/index.html`
1. Export as PDF is not yet done ([to be checked](https://www.sphinx-doc.org/en/master/usage/builders/index.html#sphinx.builders.latex.latexbuilder))

> :exclamation: Please note that in the current approach `source` dir is deleted and recreated!

> :exclamation: Current approach assumes that documentation is added in the python code (as "docstring")
> and automatically extracted here using "generate_docs.sh" script
