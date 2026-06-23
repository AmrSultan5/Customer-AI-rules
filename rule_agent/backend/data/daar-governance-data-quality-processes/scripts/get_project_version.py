#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
import re

PROJECT_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def get_project_version() -> str:
    version_path = f"{PROJECT_ROOT_DIR}/governance_data_quality_processes/__init__.py"
    with open(version_path, mode="r") as f:
        for line in f:
            version_match = re.match(r"^\s*__version__\s*=\s*[\'\"]([-._a-z0-9]+?)[\'\"].*$", line, re.IGNORECASE)
            if version_match:
                return version_match.group(1)
    raise RuntimeError(f"Unable to find version string (__version__ attribute) in file: {version_path}")


def main():
    print(get_project_version())


if __name__ == "__main__":
    main()
