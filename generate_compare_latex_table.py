#!/usr/bin/env python3

"""Generate LaTeX tables from the header/no-header comparison exports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Sequence


TEXT_LOADS = ["100", "1000", "10000", "100000"]
FILE_LOADS = ["1KB", "10KB", "100KB", "1MB", "5MB"]

TEXT_ENDPOINTS = {
    "CreateToDo": "CreateToDo Text {load}",
    "GetToDos": "GetToDos Text {load}",
    "Done": "Done Text {load}",
}

FILE_ENDPOINTS = {
    "CreateToDo": "CreateToDo File {load}",
}

CONSTANT_ENDPOINTS = {
    "Login": "Login",
    "Logout": "Logout 100",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate LaTeX comparison tables from "
            "run_compare_headers.json and run_compare_no_headers.json."
        )
    )
    parser.add_argument(
        "--headers",
        default="run_compare_headers.json",
        help="Path to the comparison export with headers enabled.",
    )
    parser.add_argument(
        "--no-headers",
        dest="no_headers",
        default="run_compare_no_headers.json",
        help="Path to the comparison export with headers disabled.",
    )
    parser.add_argument(
        "--metric",
        default="psu_energy_ac_mcp_machine",
        help="Metric key to read from each comparison entry.",
    )
    parser.add_argument(
        "--decimals",
        type=int,
        default=2,
        help="Number of decimals to print for the mWh values.",
    )
    parser.add_argument(
        "--output",
        help="Optional output file. If omitted, the LaTeX is printed to stdout.",
    )
    return parser.parse_args()


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def find_metric_stats(dataset: dict, step_name: str, metric: str) -> dict:
    scenarios = dataset["data"]["data"]
    if step_name not in scenarios:
        raise KeyError(f"Step {step_name!r} not found in input file")

    metrics = scenarios[step_name]["data"]
    if metric not in metrics:
        raise KeyError(f"Metric {metric!r} not found for step {step_name!r}")

    components = metrics[metric]["data"]
    if not components:
        raise KeyError(f"Metric {metric!r} for step {step_name!r} has no components")

    first_component = next(iter(components.values()))
    runs = first_component["data"]
    if not runs:
        raise KeyError(f"Metric {metric!r} for step {step_name!r} has no run data")

    first_run = next(iter(runs.values()))
    return {
        "mean": float(first_run["mean"]),
        "stddev": float(first_run["stddev"]),
    }


def microjoule_to_mwh(value_uj: float) -> float:
    return value_uj / 3_600_000.0


def format_value(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def format_mean_with_stddev(mean: float, stddev: float, decimals: int) -> str:
    stddev_percent = 0.0
    if mean != 0:
        stddev_percent = (stddev / mean) * 100.0
    return (
        f"{format_value(mean, decimals)} "
        f"$\\pm$ "
        f"{format_value(stddev_percent, decimals)}\\%"
    )


def format_delta(header_value: float, no_header_value: float) -> str:
    if no_header_value == 0:
        return "--"
    delta = ((header_value - no_header_value) / no_header_value) * 100.0
    return f"{delta:+.1f}\\%"


def collect_rows(
    headers_data: dict,
    no_headers_data: dict,
    metric: str,
    loads: Sequence[str],
    endpoints: Dict[str, str],
) -> List[dict]:
    rows: List[dict] = []
    for load in loads:
        endpoint_values = {}
        for endpoint_label, template in endpoints.items():
            step_name = template.format(load=load)
            header_stats = find_metric_stats(headers_data, step_name, metric)
            no_header_stats = find_metric_stats(no_headers_data, step_name, metric)
            endpoint_values[endpoint_label] = {
                "header_mean": microjoule_to_mwh(header_stats["mean"]),
                "header_stddev": microjoule_to_mwh(header_stats["stddev"]),
                "no_header_mean": microjoule_to_mwh(no_header_stats["mean"]),
                "no_header_stddev": microjoule_to_mwh(no_header_stats["stddev"]),
            }
        rows.append({"load": load, "values": endpoint_values})
    return rows


def collect_constant_rows(
    headers_data: dict,
    no_headers_data: dict,
    metric: str,
    endpoints: Dict[str, str],
) -> List[dict]:
    endpoint_values = {}
    for endpoint_label, step_name in endpoints.items():
        header_stats = find_metric_stats(headers_data, step_name, metric)
        no_header_stats = find_metric_stats(no_headers_data, step_name, metric)
        endpoint_values[endpoint_label] = {
            "header_mean": microjoule_to_mwh(header_stats["mean"]),
            "header_stddev": microjoule_to_mwh(header_stats["stddev"]),
            "no_header_mean": microjoule_to_mwh(no_header_stats["mean"]),
            "no_header_stddev": microjoule_to_mwh(no_header_stats["stddev"]),
        }
    return [{"load": "Constant", "values": endpoint_values}]


def build_table(
    *,
    caption: str,
    label: str,
    load_header: str,
    variant_header: str,
    rows: Iterable[dict],
    endpoints: Sequence[str],
    decimals: int,
) -> str:
    column_spec = "ll" + ("r" * len(endpoints))
    header_cells = " & ".join([load_header, variant_header] + list(endpoints))
    body: List[str] = [
        "\\begin{table}[h]",
        "\\centering",
        f"\\caption{{{caption}}}",
        f"\\label{{{label}}}",
        f"\\begin{{tabular}}{{{column_spec}}}",
        "\\toprule",
        f"{header_cells} \\\\",
        "\\midrule",
    ]

    row_list = list(rows)
    for row_index, row in enumerate(row_list):
        load_label = row["load"]
        values = row["values"]

        no_header_cells = [load_label, "No Header"]
        header_cells = ["", "Header"]
        delta_cells = ["", "$\\Delta$"]

        for endpoint in endpoints:
            endpoint_values = values[endpoint]
            no_header_cells.append(
                format_mean_with_stddev(
                    endpoint_values["no_header_mean"],
                    endpoint_values["no_header_stddev"],
                    decimals,
                )
            )
            header_cells.append(
                format_mean_with_stddev(
                    endpoint_values["header_mean"],
                    endpoint_values["header_stddev"],
                    decimals,
                )
            )
            delta_cells.append(
                format_delta(
                    endpoint_values["header_mean"], endpoint_values["no_header_mean"]
                )
            )

        body.append(" & ".join(no_header_cells) + " \\\\")
        body.append(" & ".join(header_cells) + " \\\\")
        body.append(" & ".join(delta_cells) + " \\\\")
        if row_index != len(row_list) - 1:
            body.append("\\midrule")

    body.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}"])
    return "\n".join(body)


def render_tables(headers_path: str, no_headers_path: str, metric: str, decimals: int) -> str:
    headers_data = load_json(headers_path)
    no_headers_data = load_json(no_headers_path)

    text_rows = collect_rows(
        headers_data=headers_data,
        no_headers_data=no_headers_data,
        metric=metric,
        loads=TEXT_LOADS,
        endpoints=TEXT_ENDPOINTS,
    )
    file_rows = collect_rows(
        headers_data=headers_data,
        no_headers_data=no_headers_data,
        metric=metric,
        loads=FILE_LOADS,
        endpoints=FILE_ENDPOINTS,
    )
    constant_rows = collect_constant_rows(
        headers_data=headers_data,
        no_headers_data=no_headers_data,
        metric=metric,
        endpoints=CONSTANT_ENDPOINTS,
    )

    constant_table = build_table(
        caption=(
            "Measured energy comparison for constant-cost authentication endpoints. "
            "Values show mean machine energy in mWh for each benchmark block."
        ),
        label="tab:compare-constant-endpoints",
        load_header="Class",
        variant_header="Variant",
        rows=constant_rows,
        endpoints=list(CONSTANT_ENDPOINTS.keys()),
        decimals=decimals,
    )

    text_table = build_table(
        caption=(
            "Measured energy comparison for text-based workload steps. "
            "Values show mean machine energy in mWh for each benchmark block."
        ),
        label="tab:compare-text-loads",
        load_header="Load",
        variant_header="Variant",
        rows=text_rows,
        endpoints=list(TEXT_ENDPOINTS.keys()),
        decimals=decimals,
    )
    file_table = build_table(
        caption=(
            "Measured energy comparison for file-upload workload steps. "
            "Values show mean machine energy in mWh for each benchmark block."
        ),
        label="tab:compare-file-loads",
        load_header="File size",
        variant_header="Variant",
        rows=file_rows,
        endpoints=list(FILE_ENDPOINTS.keys()),
        decimals=decimals,
    )

    return "\n\n".join([constant_table, text_table, file_table]) + "\n"


def main() -> None:
    args = parse_args()
    latex = render_tables(
        headers_path=args.headers,
        no_headers_path=args.no_headers,
        metric=args.metric,
        decimals=args.decimals,
    )

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(latex, encoding="utf-8")
        print(f"Wrote LaTeX tables to {output_path}")
    else:
        print(latex, end="")


if __name__ == "__main__":
    main()
