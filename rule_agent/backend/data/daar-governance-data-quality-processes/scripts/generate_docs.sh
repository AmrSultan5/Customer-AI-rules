#!/bin/sh
set -ex

PROJECT_ROOT_DIR="$(
  cd "$(dirname "$0")/.."
  pwd -P
)"
OUTPUT_DIR=$PROJECT_ROOT_DIR/docs/source
SOURCE_CODE_DIR=$PROJECT_ROOT_DIR/governance_data_quality_processes

# 1) generate .rst files using "sphinx-apidoc" into $OUTPUT_DIR and use "conf.py" and "index.rst"
# "sphinx-apidoc" documentation: https://www.sphinx-doc.org/en/master/man/sphinx-apidoc.html
# "autodoc" documentaion: http://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html
rm -rf $OUTPUT_DIR
sphinx-apidoc  --module-first --force --full -o $OUTPUT_DIR $SOURCE_CODE_DIR

# 2) copy/overwrite conf.py and index.rst (which are slightly changed) + include static and template resources
# At the end, all necessary files will be in $OUTPUT_DIR
cp $PROJECT_ROOT_DIR/docs/conf.py $OUTPUT_DIR/
cp $PROJECT_ROOT_DIR/docs/index.rst $OUTPUT_DIR/
cp -r $PROJECT_ROOT_DIR/docs/_static $OUTPUT_DIR/
cp -r $PROJECT_ROOT_DIR/docs/_templates $OUTPUT_DIR/

# 3) generate html files with actual documentation based on "autodoc" directives
cd $OUTPUT_DIR
make html SPHINXOPTS=-v
