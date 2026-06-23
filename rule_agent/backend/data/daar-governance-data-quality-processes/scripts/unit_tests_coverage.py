#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
from typing import List
from colorama import Fore

PROJECT_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
CONFIGS_DIR = f"{PROJECT_ROOT_DIR}/governance_data_quality_processes/configs/processes/"
UNIT_TESTS_DIR = f"{PROJECT_ROOT_DIR}/tests/unit"
REQUIRED_COVERAGE_PERCENT = 90


class ProcessCoverage:
    @classmethod
    def get_process_configs(cls) -> List[str]:
        process_configs = []
        for root, _, files in os.walk(CONFIGS_DIR):
            for file in files:
                if file.endswith(".yaml"):
                    cfg_path = os.path.join(root, file).replace(CONFIGS_DIR, "")
                    process_configs.append(cfg_path)
        return process_configs

    @classmethod
    def get_covered_configs(cls, process_configs: List[str]) -> List[str]:
        covered_configs = []
        for root, _, files in os.walk(UNIT_TESTS_DIR):
            for file in files:
                if file.startswith("test_") and file.endswith(".py"):
                    with open(os.path.join(root, file), mode="r") as f:
                        content_cleaned = "".join(c for c in f.read() if c.isalnum())
                        for cfg in process_configs:
                            cfg_cleaned = "".join(c for c in cfg if c.isalnum())
                            if cfg_cleaned in content_cleaned:
                                covered_configs.append(cfg)
        return covered_configs

    @classmethod
    def calculate_coverage_percent(cls, process_configs: List[str], covered_configs: List[str]) -> float:
        return round(len(covered_configs) / len(process_configs) * 100, 2)

    @classmethod
    def generate_coverage_report(
        cls, process_configs: List[str], covered_configs: List[str], coverage_percent: float
    ) -> None:
        max_len = len(max(process_configs, key=len)) + 7
        max_len = max_len if max_len >= 20 else 20
        max_len_half = int(max_len / 2)

        print(f"\n{'-' * (max_len_half - 5)} coverage {'-' * (max_len-max_len_half - 5)}")
        print(f"Name {' ' * (max_len - 11)} Cover")
        print("-" * max_len)
        for cfg in process_configs:
            covered = 100 if cfg in covered_configs else 0
            print(f"{cfg} {' ' * (max_len - len(cfg) - len(str(covered)) - 3)} {covered}%")
        print("-" * max_len)
        print(f"TOTAL {' ' * (max_len - len(str(coverage_percent)) - 8)} {coverage_percent}%")

    @classmethod
    def check_coverage(cls, coverage_percent: float) -> None:
        if coverage_percent >= REQUIRED_COVERAGE_PERCENT:
            print(
                Fore.GREEN
                + (
                    f"\nRequired test coverage of {REQUIRED_COVERAGE_PERCENT}% reached. "
                    f"Total coverage: {coverage_percent}%\n"
                )
            )
        else:
            print(
                Fore.RED
                + (
                    f"\nFAIL Required test coverage of {REQUIRED_COVERAGE_PERCENT}% not reached. "
                    f"Total coverage: {coverage_percent}%\n"
                )
            )
            raise ValueError(f"\nRequired test coverage of {REQUIRED_COVERAGE_PERCENT}% not reached\n")


def main():
    process_configs = ProcessCoverage.get_process_configs()
    covered_configs = ProcessCoverage.get_covered_configs(process_configs=process_configs)
    coverage_percent = ProcessCoverage.calculate_coverage_percent(
        process_configs=process_configs, covered_configs=covered_configs
    )
    ProcessCoverage.generate_coverage_report(
        process_configs=process_configs, covered_configs=covered_configs, coverage_percent=coverage_percent
    )
    ProcessCoverage.check_coverage(coverage_percent=coverage_percent)


if __name__ == "__main__":
    main()
