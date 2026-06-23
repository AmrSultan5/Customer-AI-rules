import os
from scripts.get_project_version import get_project_version

import setuptools

PROJECT_ROOT_DIR = os.path.dirname(os.path.realpath(__file__))


def get_project_long_description() -> str:
    with open(f"{PROJECT_ROOT_DIR}/README.md", "r") as f:
        return f.read()


def get_project_requirements() -> str:
    with open(f"{PROJECT_ROOT_DIR}/requirements.txt", "r") as f:
        return f.read()


def package_files(directory):
    paths = []
    for (path, _, filenames) in os.walk(directory):
        for filename in filenames:
            paths.append(os.path.join("..", path, filename))
    return paths


configs = package_files("governance_data_quality_processes/configs")

setuptools.setup(
    name="governance-data-quality-processes",
    description="Data Mesh ETL Processes",
    version=get_project_version(),
    long_description=get_project_long_description(),
    long_description_content_type="text/markdown",
    python_requires=">=3.8",
    license="Proprietary",
    packages=setuptools.find_packages(include=["governance_data_quality_processes", "governance_data_quality_processes.*"]),
    package_data={"": [*configs]},
    install_requires=get_project_requirements(),
)
