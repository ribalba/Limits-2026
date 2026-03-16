#!/usr/bin/env python3
"""Generate url_energy.json from a Green Coding comparison export."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path


UOJ_PER_MWH = 3_600_000.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a per-route energy registry from a Green Coding export and "
            "the benchmark scenario definition."
        )
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="Path to the Green Coding JSON export, or '-' for stdin.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="code/url_energy.json",
        help="Output path for the generated registry.",
    )
    parser.add_argument(
        "--scenario",
        default="code/usage_scenario.yml",
        help="Path to usage_scenario.yml.",
    )
    parser.add_argument(
        "--idle-phase",
        default="[IDLE]",
        help="Phase name used as the idle baseline for subtraction.",
    )
    parser.add_argument(
        "--baseline-phase",
        default="[BASELINE]",
        help="Fallback phase name used for shared carbon metadata.",
    )
    parser.add_argument(
        "--no-idle-subtraction",
        action="store_true",
        help="Use raw machine energy instead of subtracting the idle baseline.",
    )
    parser.add_argument(
        "--ai-token-map",
        help=(
            "Optional JSON file with token counts per AI phase. Supported keys are "
            "phase names or profile aliases like 'very-short'."
        ),
    )
    parser.add_argument(
        "--ai-bench-stdout",
        help=(
            "Optional ai_bench.sh stdout file. The generator will parse prompt and "
            "generated token counts and average them by AI profile."
        ),
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help=(
            "Write a compact pretty-printed JSON file with floats rounded to 3 "
            "decimals and arrays kept on one line."
        ),
    )
    return parser.parse_args()


def load_json(path: str) -> dict:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text())


def parse_scenario(path: Path) -> dict[str, dict]:
    phase_meta: dict[str, dict] = {}
    current_name: str | None = None

    for raw_line in path.read_text().splitlines():
        name_match = re.match(r"\s*-\s+name:\s+(.*)\s*$", raw_line)
        if name_match:
            current_name = name_match.group(1).strip()
            phase_meta[current_name] = {"requests": 1}
            continue

        if current_name is None:
            continue

        cmd_match = re.match(r"\s*command:\s+(.*)\s*$", raw_line)
        if not cmd_match:
            continue

        command = cmd_match.group(1).strip()
        phase_meta[current_name].update(parse_command_metadata(current_name, command))

    return phase_meta


def parse_command_metadata(phase_name: str, command: str) -> dict:
    meta = {"requests": 1}
    script_match = re.search(r"/([^/\s]+\.sh)\b", command)
    n_match = re.search(r"(?:^|\s)-n\s+(\d+)\b", command)
    text_match = re.search(r"(?:^|\s)-t\s+(\d+)\b", command)
    file_match = re.search(r"(?:^|\s)-f\s+(\d+)\b", command)

    script = script_match.group(1) if script_match else ""
    count = int(n_match.group(1)) if n_match else 1
    text_length = int(text_match.group(1)) if text_match else 0
    file_size = int(file_match.group(1)) if file_match else 0

    if script in {
        "login_bench.sh",
        "logout_bench.sh",
        "create_todo_bench.sh",
        "get_todos_bench.sh",
        "ai_bench.sh",
        "delete_all_todos_bench.sh",
    }:
        meta["requests"] = count
    elif script == "done_bench.sh":
        # The scenario creates 100 todos before each done phase, so `-n 1`
        # still issues 100 POST /done requests.
        meta["requests"] = 100 * count
    else:
        meta["requests"] = count

    if phase_name.startswith("CreateToDo "):
        meta["input_bytes"] = text_length + file_size

    return meta


def extract_phases(payload: dict) -> dict[str, dict]:
    phase_root = payload.get("data", {}).get("data")
    if not isinstance(phase_root, dict):
        raise ValueError("Could not find payload['data']['data'] in the export.")
    return phase_root


def metric_value(
    phases: dict[str, dict],
    phase_name: str,
    metric_name: str,
    entity_name: str | None = None,
) -> float | None:
    phase = phases.get(phase_name)
    if not phase:
        return None

    metric = phase.get("data", {}).get(metric_name)
    if not metric:
        return None

    entities = metric.get("data", {})
    if not entities:
        return None

    if entity_name is None:
        entity = next(iter(entities.values()), None)
    else:
        entity = entities.get(entity_name)
    if not entity:
        return None

    samples = entity.get("data", {})
    if not samples:
        return None

    sample = next(iter(samples.values()), None)
    if not sample:
        return None

    value = sample.get("mean")
    if value is None:
        return None
    return float(value)


def network_proxy_bytes(phases: dict[str, dict], phase_name: str) -> float | None:
    phase = phases.get(phase_name)
    if not phase:
        return None

    metric = phase.get("data", {}).get("network_total_cgroup_container")
    if not metric:
        return None

    entities = metric.get("data", {})
    if not entities:
        return None

    values: list[float] = []
    for entity in entities.values():
        samples = entity.get("data", {})
        if not samples:
            continue
        sample = next(iter(samples.values()), None)
        if not sample or sample.get("mean") is None:
            continue
        values.append(float(sample["mean"]))

    if not values:
        return None

    return max(values)


def make_phase_record(
    phases: dict[str, dict],
    phase_name: str,
    meta: dict,
    idle_power_uw: float | None,
    subtract_idle: bool,
) -> dict | None:
    time_us = metric_value(phases, phase_name, "phase_time_syscall_system", "[SYSTEM]")
    energy_uj = metric_value(phases, phase_name, "psu_energy_ac_mcp_machine", "[MACHINE]")
    if time_us is None or energy_uj is None:
        return None

    requests = max(int(meta.get("requests", 1)), 1)
    time_sec = time_us / 1_000_000.0
    adjusted_energy_uj = energy_uj
    if subtract_idle and idle_power_uw is not None:
        adjusted_energy_uj = max(0.0, energy_uj - idle_power_uw * time_sec)

    record = {
        "phase": phase_name,
        "requests": requests,
        "time_sec": time_sec,
        "energy_mwh_per_request": adjusted_energy_uj / UOJ_PER_MWH / requests,
    }

    input_bytes = meta.get("input_bytes")
    if input_bytes is not None:
        record["input_bytes"] = float(input_bytes)

    network_total = network_proxy_bytes(phases, phase_name)
    if network_total is not None:
        record["network_bytes_per_request"] = network_total / requests

    return record


def route_for_phase(phase_name: str) -> str | None:
    if phase_name == "Login":
        return "/login"
    if phase_name.startswith("Logout"):
        return "/logout"
    if phase_name.startswith("CreateToDo "):
        return "/createToDo"
    if phase_name.startswith("GetToDos "):
        return "/getToDos"
    if phase_name.startswith("Done "):
        return "/done"
    if phase_name.startswith("Cleanup "):
        return "/deleteAllToDos"
    if phase_name.startswith("AI "):
        return "/ai"
    return None


def dedupe_points(points: list[list[float]]) -> list[list[float]]:
    grouped: dict[float, list[float]] = {}
    for x_value, y_value in points:
        grouped.setdefault(float(x_value), []).append(float(y_value))

    return [
        [x_value, sum(y_values) / len(y_values)]
        for x_value, y_values in sorted(grouped.items())
    ]


def build_constant(records: list[dict]) -> dict:
    value = sum(item["energy_mwh_per_request"] for item in records) / len(records)
    return {"kind": "constant", "value_mWh": value}


def build_curve(records: list[dict], x_key: str, input_name: str) -> dict:
    points = [
        [item[x_key], item["energy_mwh_per_request"]]
        for item in records
        if x_key in item
    ]
    if not points:
        return build_constant(records)

    return {
        "kind": "curve",
        "input": input_name,
        "points": dedupe_points(points),
        "interpolate": "linear",
        "extrapolate": "linear_tail",
    }


def load_ai_token_map(path: str | None) -> dict[str, dict]:
    if not path:
        return {}
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, dict):
        raise ValueError("AI token map must be a JSON object.")
    return raw


def load_ai_bench_stdout(path: str | None) -> dict[str, dict]:
    if not path:
        return {}

    pattern = re.compile(r"([a-z_]+)=([^\s]+)")
    grouped: dict[str, list[dict[str, float]]] = {}

    for raw_line in Path(path).read_text().splitlines():
        fields = dict(pattern.findall(raw_line))
        profile = fields.get("prompt_profile")
        prompt_tokens = fields.get("prompt_tokens")
        generated_tokens = fields.get("generated_tokens")
        if not profile or prompt_tokens is None or generated_tokens is None:
            continue

        try:
            sample = {
                "prompt_tokens": float(prompt_tokens),
                "generated_tokens": float(generated_tokens),
            }
        except ValueError:
            continue

        grouped.setdefault(profile, []).append(sample)

    averaged: dict[str, dict] = {}
    for profile, samples in grouped.items():
        prompt_avg = sum(item["prompt_tokens"] for item in samples) / len(samples)
        generated_avg = sum(item["generated_tokens"] for item in samples) / len(samples)
        averaged[profile] = {
            "prompt_tokens": prompt_avg,
            "generated_tokens": generated_avg,
            "total_tokens": prompt_avg + generated_avg,
            "samples": len(samples),
        }

    return averaged


def merge_ai_token_sources(*sources: dict[str, dict]) -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for source in sources:
        for key, value in source.items():
            merged[key] = value
    return merged


def round_floats(value):
    if isinstance(value, float):
        rounded = round(value, 3)
        if rounded == 0:
            rounded = 0.0
        return rounded
    if isinstance(value, list):
        return [round_floats(item) for item in value]
    if isinstance(value, dict):
        return {key: round_floats(item) for key, item in value.items()}
    return value


def dump_pretty_json(value, level: int = 0) -> str:
    indent = "  " * level
    next_indent = "  " * (level + 1)

    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = []
        for key, item in value.items():
            lines.append(f'{next_indent}{json.dumps(key)}: {dump_pretty_json(item, level + 1)}')
        return "{\n" + ",\n".join(lines) + "\n" + indent + "}"

    if isinstance(value, list):
        return "[" + ", ".join(dump_pretty_json(item, 0) for item in value) + "]"

    return json.dumps(value)


def ai_phase_alias(phase_name: str) -> str:
    lowered = phase_name.lower()
    if "very short" in lowered:
        return "very-short"
    if "very long" in lowered:
        return "very-long"
    if "short" in lowered:
        return "short"
    if "medium" in lowered:
        return "medium"
    if "long" in lowered:
        return "long"
    return phase_name


def ai_features_for_phase(token_map: dict[str, dict], phase_name: str) -> dict | None:
    phase_keys = [phase_name, ai_phase_alias(phase_name)]
    for key in phase_keys:
        entry = token_map.get(key)
        if not isinstance(entry, dict):
            continue

        prompt_tokens = entry.get("prompt_tokens")
        generated_tokens = entry.get("generated_tokens")
        total_tokens = entry.get("total_tokens")

        if prompt_tokens is not None and generated_tokens is not None:
            return {
                "prompt_tokens": float(prompt_tokens),
                "generated_tokens": float(generated_tokens),
            }

        if total_tokens is not None:
            return {"total_tokens": float(total_tokens)}

    return None


def solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    size = len(vector)
    augmented = [row[:] + [vector[idx]] for idx, row in enumerate(matrix)]

    for pivot in range(size):
        pivot_row = max(range(pivot, size), key=lambda row: abs(augmented[row][pivot]))
        if abs(augmented[pivot_row][pivot]) < 1e-12:
            return None
        augmented[pivot], augmented[pivot_row] = augmented[pivot_row], augmented[pivot]

        factor = augmented[pivot][pivot]
        for column in range(pivot, size + 1):
            augmented[pivot][column] /= factor

        for row in range(size):
            if row == pivot:
                continue
            factor = augmented[row][pivot]
            for column in range(pivot, size + 1):
                augmented[row][column] -= factor * augmented[pivot][column]

    return [augmented[row][size] for row in range(size)]


def fit_simple_linear(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None

    xtx = [[0.0, 0.0], [0.0, 0.0]]
    xty = [0.0, 0.0]
    for x_val, y_val in zip(xs, ys):
        row = [1.0, x_val]
        for i in range(2):
            xty[i] += row[i] * y_val
            for j in range(2):
                xtx[i][j] += row[i] * row[j]

    coeffs = solve_linear_system(xtx, xty)
    if coeffs is None or not all(math.isfinite(value) for value in coeffs):
        return None
    return coeffs[0], coeffs[1]


def fit_ai_model(records: list[dict], token_map: dict[str, dict]) -> tuple[dict, str | None]:
    samples: list[dict] = []
    for item in records:
        features = ai_features_for_phase(token_map, item["phase"])
        if features is None:
            continue
        sample = {"energy": item["energy_mwh_per_request"]}
        sample.update(features)
        samples.append(sample)

    if len(samples) < 2:
        time_fit = fit_simple_linear(
            [item["time_sec"] / item["requests"] for item in records],
            [item["energy_mwh_per_request"] for item in records],
        )
        if time_fit is not None:
            intercept, slope = time_fit
            return {
                "kind": "linear",
                "intercept_mWh": intercept,
                "time_coeff_mWh_per_s": slope,
            }, (
                "AI token counts were missing or insufficient; using a time-based "
                "fallback model instead."
            )
        return build_constant(records), (
            "AI phases were present, but token counts were missing or insufficient; "
            "falling back to a constant model."
        )

    if all("prompt_tokens" in sample and "generated_tokens" in sample for sample in samples):
        xtx = [[0.0, 0.0, 0.0] for _ in range(3)]
        xty = [0.0, 0.0, 0.0]
        for sample in samples:
            row = [1.0, sample["prompt_tokens"], sample["generated_tokens"]]
            y_val = sample["energy"]
            for i in range(3):
                xty[i] += row[i] * y_val
                for j in range(3):
                    xtx[i][j] += row[i] * row[j]
        coeffs = solve_linear_system(xtx, xty)
        if coeffs is not None and all(math.isfinite(value) for value in coeffs):
            return {
                "kind": "linear",
                "intercept_mWh": coeffs[0],
                "prompt_token_coeff_mWh_per_token": coeffs[1],
                "generated_token_coeff_mWh_per_token": coeffs[2],
            }, None

    if all("total_tokens" in sample for sample in samples):
        xtx = [[0.0, 0.0], [0.0, 0.0]]
        xty = [0.0, 0.0]
        for sample in samples:
            row = [1.0, sample["total_tokens"]]
            y_val = sample["energy"]
            for i in range(2):
                xty[i] += row[i] * y_val
                for j in range(2):
                    xtx[i][j] += row[i] * row[j]
        coeffs = solve_linear_system(xtx, xty)
        if coeffs is not None and all(math.isfinite(value) for value in coeffs):
            return {
                "kind": "linear",
                "intercept_mWh": coeffs[0],
                "token_coeff_mWh_per_token": coeffs[1],
            }, None

    time_fit = fit_simple_linear(
        [item["time_sec"] / item["requests"] for item in records],
        [item["energy_mwh_per_request"] for item in records],
    )
    if time_fit is not None:
        intercept, slope = time_fit
        return {
            "kind": "linear",
            "intercept_mWh": intercept,
            "time_coeff_mWh_per_s": slope,
        }, (
            "AI token metadata was present but could not be fit cleanly; "
            "using a time-based fallback model instead."
        )

    return build_constant(records), (
        "AI token metadata was present but could not be fit cleanly; "
        "falling back to a constant model."
    )


def derive_shared_values(
    phases: dict[str, dict],
    idle_phase: str,
    baseline_phase: str,
) -> tuple[float, float, float | None]:
    reference_names = [idle_phase, baseline_phase] + [
        name for name in phases if name not in {idle_phase, baseline_phase}
    ]

    idle_power_uw = None
    idle_energy_uj = metric_value(phases, idle_phase, "psu_energy_ac_mcp_machine", "[MACHINE]")
    idle_time_us = metric_value(phases, idle_phase, "phase_time_syscall_system", "[SYSTEM]")
    if idle_energy_uj is not None and idle_time_us and idle_time_us > 0:
        idle_power_uw = idle_energy_uj / (idle_time_us / 1_000_000.0)

    grid_intensity = 0.0
    embodied_rate = 0.0

    for phase_name in reference_names:
        energy_uj = metric_value(phases, phase_name, "psu_energy_ac_mcp_machine", "[MACHINE]")
        carbon_ug = metric_value(phases, phase_name, "psu_carbon_ac_mcp_machine", "[MACHINE]")
        embodied_ug = metric_value(phases, phase_name, "embodied_carbon_share_machine", "[SYSTEM]")
        time_us = metric_value(phases, phase_name, "phase_time_syscall_system", "[SYSTEM]")

        if grid_intensity == 0.0 and energy_uj and carbon_ug:
            grid_intensity = carbon_ug / energy_uj * 1_000_000.0
        if embodied_rate == 0.0 and embodied_ug is not None and time_us and time_us > 0:
            # ug / us is numerically identical to g / s.
            embodied_rate = embodied_ug / time_us
        if grid_intensity > 0.0 and embodied_rate > 0.0:
            break

    return grid_intensity, embodied_rate, idle_power_uw


def build_registry(
    phases: dict[str, dict],
    scenario_meta: dict[str, dict],
    idle_phase: str,
    baseline_phase: str,
    subtract_idle: bool,
    ai_token_map: dict[str, dict],
) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    grid_intensity, embodied_rate, idle_power_uw = derive_shared_values(
        phases, idle_phase, baseline_phase
    )

    by_route: dict[str, list[dict]] = {}
    for phase_name, meta in scenario_meta.items():
        route = route_for_phase(phase_name)
        if route is None:
            continue
        record = make_phase_record(
            phases=phases,
            phase_name=phase_name,
            meta=meta,
            idle_power_uw=idle_power_uw,
            subtract_idle=subtract_idle,
        )
        if record is None:
            warnings.append(f"Skipping phase '{phase_name}' because required metrics were missing.")
            continue
        by_route.setdefault(route, []).append(record)

    registry: dict[str, dict] = {}
    for route, records in sorted(by_route.items()):
        if route == "/createToDo":
            energy_model = build_curve(records, "input_bytes", "data_size")
        elif route == "/getToDos":
            energy_model = build_curve(records, "network_bytes_per_request", "data_size")
        elif route == "/ai":
            energy_model, warning = fit_ai_model(records, ai_token_map)
            if warning:
                warnings.append(warning)
        else:
            energy_model = build_constant(records)

        registry[route] = {
            "energy_model": energy_model,
            "embodied_rate_gCO2e_per_s": embodied_rate,
            "grid_intensity_gCO2e_per_kWh": grid_intensity,
        }

    return registry, warnings


def main() -> int:
    args = parse_args()

    payload = load_json(args.input)
    phases = extract_phases(payload)
    scenario_meta = parse_scenario(Path(args.scenario))
    ai_token_map = merge_ai_token_sources(
        load_ai_bench_stdout(args.ai_bench_stdout),
        load_ai_token_map(args.ai_token_map),
    )

    registry, warnings = build_registry(
        phases=phases,
        scenario_meta=scenario_meta,
        idle_phase=args.idle_phase,
        baseline_phase=args.baseline_phase,
        subtract_idle=not args.no_idle_subtraction,
        ai_token_map=ai_token_map,
    )

    if not registry:
        print("No route models could be generated from the provided export.", file=sys.stderr)
        return 1

    output_path = Path(args.output)
    if args.pretty:
        formatted = dump_pretty_json(round_floats(registry))
    else:
        formatted = json.dumps(registry, indent=2, sort_keys=True)
    output_path.write_text(formatted + "\n")

    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)

    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
