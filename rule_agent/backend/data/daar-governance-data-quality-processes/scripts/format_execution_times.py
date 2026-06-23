#!/usr/bin/python3
# -*- coding: utf-8 -*-

import argparse
import csv
import logging
from collections import defaultdict
from statistics import StatisticsError, mean, median, stdev
from typing import Dict, Iterable, List, Tuple, Union

from tabulate import tabulate

Row = List[Union[str, float, int]]


def log_warning(message: str) -> None:
    logging.warning(message)


def safe_stdev(execution_times: List[float]) -> float:
    try:
        return stdev(execution_times)
    except StatisticsError as e:
        log_warning(f"{stdev.__name__}: {e}")
        return 0


class ExecutionTimesFormatter:
    @classmethod
    def process(cls, execution_times_file_path: str) -> None:
        input_rows_header = ["function_name", "direct_caller", "log_timestamp", "elapsed_seconds"]
        input_rows = cls._load_csv(execution_times_file_path)
        function_execution_times = cls._group_execution_times_by_function_name(input_rows)
        functions_statistics_header, functions_statistics = cls._calculate_statistics(function_execution_times)
        cls._show_functions_statistics(functions_statistics_header, functions_statistics)
        cls._show_raw_input_data(input_rows_header, input_rows)

    @classmethod
    def _load_csv(cls, execution_times_file_path: str) -> List[Row]:
        rows = list()
        try:
            with open(execution_times_file_path, newline="") as f:
                for row in csv.reader(f, delimiter="\t"):
                    rows.append(row)
        except FileNotFoundError:
            log_warning(f"Input path does not exists! Input path: {execution_times_file_path}")
        return rows  # type: ignore

    @classmethod
    def _group_execution_times_by_function_name(cls, rows: List[Row]) -> Dict[str, List[float]]:
        function_execution_times = defaultdict(list)
        for row in rows:
            func_name = row[0]  # first column
            execution_time = row[-1]  # last column
            function_execution_times[func_name].append(float(execution_time))
        return function_execution_times  # type: ignore

    @classmethod
    def _calculate_statistics(cls, function_execution_times: Dict[str, List[float]]) -> Tuple[List[str], List[Row]]:
        header = ["function_name", "count", "sum", "min", "max", "average", "median", "stdev", "top_5_longest"]
        functions_statistics = []
        for func_name, execution_times in function_execution_times.items():
            assert len(execution_times) > 0
            execution_times = sorted(execution_times, reverse=True)
            func_stats = [
                len(execution_times),
                sum(execution_times),
                min(execution_times),
                max(execution_times),
                mean(execution_times),
                median(execution_times),
                safe_stdev(execution_times),
                execution_times[:5],
            ]
            functions_statistics.append([func_name, *func_stats])

        assert all(len(header) == len(row) for row in functions_statistics), "header and row have different lengths!!!"
        return header, functions_statistics  # type: ignore

    @classmethod
    def _show_functions_statistics(cls, header: List[str], functions_statistics: Iterable[Row]) -> None:
        print()
        print(tabulate(tabular_data=sorted(functions_statistics), headers=header, floatfmt=".1f"))
        print()

    @classmethod
    def _show_raw_input_data(cls, header: List[str], rows: List[Row]) -> None:
        print()
        print(tabulate(tabular_data=sorted(rows), headers=header))
        print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("execution_times_file_path")
    args = parser.parse_args()
    ExecutionTimesFormatter.process(args.execution_times_file_path)


if __name__ == "__main__":
    main()
