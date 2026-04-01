#!/usr/bin/env python3
"""Estimate total request energy and carbon from structured nginx access logs."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay the url_energy registry against structured nginx access logs "
            "and aggregate total estimated request energy and carbon."
        )
    )
    parser.add_argument(
        "input",
        help="Path to the JSON-lines nginx access log.",
    )
    parser.add_argument(
        "-r",
        "--registry",
        default="code/url_energy.json",
        help="Path to url_energy.json.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the summary as JSON instead of human-readable text.",
    )
    return parser.parse_args()


def to_number(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(number):
        return fallback
    return number


def clamp_non_negative(value: float) -> float:
    return value if value >= 0 else 0.0


def normalize_path(path: str | None) -> str:
    if not path:
        return "/"
    normalized = str(path).split("?", 1)[0]
    if len(normalized) > 1 and normalized.endswith("/"):
        return normalized[:-1]
    return normalized or "/"


def normalize_method(method: Any) -> str:
    if method in (None, ""):
        return ""
    return str(method).upper()


def parse_time_seconds(value: Any) -> float:
    if value in (None, "", "-"):
        return 0.0
    text = str(value)
    if "," in text:
        text = text.split(",", 1)[0]
    text = text.strip()
    if not text or text == "-":
        return 0.0
    return to_number(text, 0.0)


def data_size_bytes(entry: dict[str, Any]) -> float:
    request_bytes = to_number(entry.get("request_length"), 0.0)
    response_bytes = to_number(entry.get("body_bytes_sent"), 0.0)
    return max(request_bytes, response_bytes)


def feature_code(input_name: str | None) -> str:
    if input_name == "time":
        return "time"
    if input_name == "prompt_tokens":
        return "prompt_tokens"
    if input_name == "generated_tokens":
        return "generated_tokens"
    if input_name in {"total_tokens", "token_count", "tokens"}:
        return "total_tokens"
    return "data_size"


def point_pair(raw_point: Any) -> tuple[float, float] | None:
    if not isinstance(raw_point, list) or len(raw_point) < 2:
        return None
    x_value = to_number(raw_point[0], math.nan)
    y_value = to_number(raw_point[1], math.nan)
    if not math.isfinite(x_value) or not math.isfinite(y_value):
        return None
    return x_value, y_value


def compile_route_config(route_config: dict[str, Any]) -> dict[str, Any]:
    model = route_config.get("energy_model")
    compiled: dict[str, Any] = {
        "filter": None,
        "embodied_rate": to_number(route_config.get("embodied_rate_gCO2e_per_s"), 0.0),
        "grid_intensity": to_number(route_config.get("grid_intensity_gCO2e_per_kWh"), 0.0),
        "kind": "constant",
        "constant_energy": 0.0,
        "intercept": 0.0,
        "time_coeff": 0.0,
        "size_coeff": 0.0,
        "token_coeff": 0.0,
        "prompt_token_coeff": 0.0,
        "generated_token_coeff": 0.0,
        "curve_input": "data_size",
        "curve_points": [],
        "curve_clamp": False,
    }
    raw_filter = route_config.get("filter")
    if isinstance(raw_filter, dict):
        if isinstance(raw_filter.get("method"), str) and raw_filter.get("method"):
            compiled["filter"] = {"method": normalize_method(raw_filter["method"])}
        elif isinstance(raw_filter.get("methods"), list):
            methods = [
                normalize_method(method)
                for method in raw_filter["methods"]
                if normalize_method(method)
            ]
            if methods:
                compiled["filter"] = {"methods": methods}

    if isinstance(model, (int, float)):
        compiled["constant_energy"] = clamp_non_negative(float(model))
        return compiled

    kind = "constant"
    if isinstance(model, dict):
        kind = str(model.get("kind", "constant"))
    compiled["kind"] = kind

    if kind == "linear" and isinstance(model, dict):
        compiled["intercept"] = to_number(model.get("intercept_mWh"), 0.0)
        compiled["time_coeff"] = to_number(model.get("time_coeff_mWh_per_s"), 0.0)
        compiled["size_coeff"] = to_number(model.get("size_coeff_mWh_per_byte"), 0.0)
        compiled["token_coeff"] = to_number(model.get("token_coeff_mWh_per_token"), 0.0)
        compiled["prompt_token_coeff"] = to_number(
            model.get("prompt_token_coeff_mWh_per_token"), 0.0
        )
        compiled["generated_token_coeff"] = to_number(
            model.get("generated_token_coeff_mWh_per_token"), 0.0
        )
        return compiled

    if kind == "curve" and isinstance(model, dict):
        compiled["curve_input"] = feature_code(str(model.get("input", "data_size")))
        compiled["curve_clamp"] = model.get("extrapolate") == "clamp"
        points: list[tuple[float, float]] = []
        for raw_point in model.get("points", []):
            pair = point_pair(raw_point)
            if pair is not None:
                points.append(pair)
        points.sort(key=lambda pair: pair[0])
        compiled["curve_points"] = points
        return compiled

    if isinstance(model, dict):
        compiled["constant_energy"] = clamp_non_negative(to_number(model.get("value_mWh"), 0.0))
    return compiled


def compile_registry(registry: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    compiled: dict[str, list[dict[str, Any]]] = {}
    for route, route_config in registry.items():
        variants: list[dict[str, Any]] = []
        if isinstance(route_config, dict):
            variants = [compile_route_config(route_config)]
        elif isinstance(route_config, list):
            variants = [
                compile_route_config(item)
                for item in route_config
                if isinstance(item, dict)
            ]
        if variants:
            compiled[normalize_path(route)] = variants
    return compiled


def filter_matches(filter_spec: dict[str, Any] | None, request_method: str) -> bool:
    if not filter_spec:
        return False
    if "method" in filter_spec:
        return filter_spec["method"] == request_method
    if "methods" in filter_spec:
        return request_method in filter_spec["methods"]
    return False


def select_route_config(
    route_configs: list[dict[str, Any]] | None, request_method: str
) -> dict[str, Any] | None:
    if not route_configs:
        return None

    fallback = None
    for route_config in route_configs:
        if not route_config.get("filter") and fallback is None:
            fallback = route_config
        if filter_matches(route_config.get("filter"), request_method):
            return route_config
    return fallback


def feature_value(
    input_code: str,
    time_sec: float,
    data_size: float,
    total_tokens: float,
    prompt_tokens: float,
    generated_tokens: float,
) -> float:
    if input_code == "time":
        return time_sec
    if input_code == "prompt_tokens":
        return prompt_tokens
    if input_code == "generated_tokens":
        return generated_tokens
    if input_code == "total_tokens":
        return total_tokens
    return data_size


def linear_interpolate(x_value: float, left: tuple[float, float], right: tuple[float, float]) -> float:
    x0, y0 = left
    x1, y1 = right
    if x1 == x0:
        return y1
    return y0 + ((x_value - x0) * (y1 - y0)) / (x1 - x0)


def evaluate_curve(
    points: list[tuple[float, float]],
    clamp: bool,
    input_code: str,
    time_sec: float,
    data_size: float,
    total_tokens: float,
    prompt_tokens: float,
    generated_tokens: float,
) -> float:
    if not points:
        return 0.0

    x_value = feature_value(
        input_code,
        time_sec,
        data_size,
        total_tokens,
        prompt_tokens,
        generated_tokens,
    )

    left = points[0]
    right = points[-1]

    if x_value <= left[0]:
        if clamp or len(points) < 2:
            return left[1]
        return linear_interpolate(x_value, left, points[1])

    if x_value >= right[0]:
        if clamp or len(points) < 2:
            return right[1]
        return linear_interpolate(x_value, points[-2], right)

    for idx in range(len(points) - 1):
        left = points[idx]
        right = points[idx + 1]
        if x_value <= right[0]:
            return linear_interpolate(x_value, left, right)

    return right[1]


def evaluate_energy(
    route_config: dict[str, Any],
    time_sec: float,
    data_size: float,
    total_tokens: float,
    prompt_tokens: float,
    generated_tokens: float,
) -> float:
    kind = route_config["kind"]

    if kind == "constant":
        return route_config["constant_energy"]

    if kind == "linear":
        return clamp_non_negative(
            route_config["intercept"]
            + route_config["time_coeff"] * time_sec
            + route_config["size_coeff"] * data_size
            + route_config["token_coeff"] * total_tokens
            + route_config["prompt_token_coeff"] * prompt_tokens
            + route_config["generated_token_coeff"] * generated_tokens
        )

    if kind == "curve":
        return clamp_non_negative(
            evaluate_curve(
                route_config["curve_points"],
                route_config["curve_clamp"],
                route_config["curve_input"],
                time_sec,
                data_size,
                total_tokens,
                prompt_tokens,
                generated_tokens,
            )
        )

    return 0.0


def rounded(value: float) -> float:
    result = round(value, 3)
    if result == 0:
        return 0.0
    return result


def new_bucket() -> dict[str, float]:
    return {
        "requests": 0,
        "energy_mWh": 0.0,
        "operational_mgCO2e": 0.0,
        "embodied_mgCO2e": 0.0,
        "total_mgCO2e": 0.0,
        "request_seconds": 0.0,
    }


def add_bucket(target: dict[str, float], delta: dict[str, float]) -> None:
    for key, value in delta.items():
        target[key] += value


def bucket_with_request(
    energy_mwh: float,
    operational_mg: float,
    embodied_mg: float,
    total_mg: float,
    time_sec: float,
) -> dict[str, float]:
    return {
        "requests": 1,
        "energy_mWh": energy_mwh,
        "operational_mgCO2e": operational_mg,
        "embodied_mgCO2e": embodied_mg,
        "total_mgCO2e": total_mg,
        "request_seconds": time_sec,
    }


def summarize(log_path: Path, registry_path: Path) -> dict[str, Any]:
    compiled_registry = compile_registry(json.loads(registry_path.read_text()))

    totals = new_bucket()
    by_route: dict[str, dict[str, float]] = {}
    skipped_lines = 0
    skipped_requests = 0
    unknown_routes: dict[str, int] = {}

    for line_number, raw_line in enumerate(log_path.read_text().splitlines(), start=1):
        if not raw_line.strip():
            continue

        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            skipped_lines += 1
            print(f"warning: line {line_number} is not valid JSON and was skipped", file=sys.stderr)
            continue

        route = normalize_path(entry.get("uri") or entry.get("request_uri"))
        request_method = normalize_method(entry.get("method"))
        route_config = select_route_config(compiled_registry.get(route), request_method)
        if route_config is None:
            skipped_requests += 1
            unknown_routes[route] = unknown_routes.get(route, 0) + 1
            continue

        time_sec = parse_time_seconds(entry.get("upstream_response_time"))
        if time_sec <= 0:
            time_sec = parse_time_seconds(entry.get("request_time"))

        prompt_tokens = to_number(entry.get("prompt_tokens"), 0.0)
        generated_tokens = to_number(entry.get("generated_tokens"), 0.0)
        total_tokens = prompt_tokens + generated_tokens
        data_size = data_size_bytes(entry)

        energy_mwh = evaluate_energy(
            route_config,
            time_sec,
            data_size,
            total_tokens,
            prompt_tokens,
            generated_tokens,
        )
        operational_mg = energy_mwh * route_config["grid_intensity"] / 1000.0
        embodied_mg = route_config["embodied_rate"] * 1000.0 * time_sec
        total_mg = operational_mg + embodied_mg

        request_bucket = bucket_with_request(
            energy_mwh=energy_mwh,
            operational_mg=operational_mg,
            embodied_mg=embodied_mg,
            total_mg=total_mg,
            time_sec=time_sec,
        )
        add_bucket(totals, request_bucket)
        add_bucket(by_route.setdefault(route, new_bucket()), request_bucket)

    rounded_totals = {
        key: (int(value) if key == "requests" else rounded(value))
        for key, value in totals.items()
    }
    rounded_routes = {}
    for route, bucket in sorted(by_route.items()):
        rounded_routes[route] = {
            key: (int(value) if key == "requests" else rounded(value))
            for key, value in bucket.items()
        }

    return {
        "log_path": str(log_path),
        "registry_path": str(registry_path),
        "processed_requests": rounded_totals["requests"],
        "skipped_lines": skipped_lines,
        "skipped_requests": skipped_requests,
        "unknown_routes": unknown_routes,
        "totals": rounded_totals,
        "by_route": rounded_routes,
    }


def print_human(summary: dict[str, Any]) -> None:
    print(f"Log file: {summary['log_path']}")
    print(f"Registry: {summary['registry_path']}")
    print(f"Processed requests: {summary['processed_requests']}")
    print(f"Skipped lines: {summary['skipped_lines']}")
    print(f"Skipped requests: {summary['skipped_requests']}")
    print(f"Total energy: {summary['totals']['energy_mWh']} mWh")
    print(f"Operational carbon: {summary['totals']['operational_mgCO2e']} mgCO2e")
    print(f"Embodied carbon: {summary['totals']['embodied_mgCO2e']} mgCO2e")
    print(f"Total carbon: {summary['totals']['total_mgCO2e']} mgCO2e")
    print("")
    print("Per route:")
    for route, bucket in summary["by_route"].items():
        print(
            f"  {route}: requests={bucket['requests']} energy_mWh={bucket['energy_mWh']} "
            f"total_mgCO2e={bucket['total_mgCO2e']}"
        )
    if summary["unknown_routes"]:
        print("")
        print("Skipped routes:")
        for route, count in sorted(summary["unknown_routes"].items()):
            print(f"  {route}: {count}")


def main() -> int:
    args = parse_args()
    summary = summarize(Path(args.input), Path(args.registry))

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print_human(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
