#!/usr/bin/env python3
"""Plot tension-only hysteresis loops from EPOS CSV logs.

The logger writes raw load-cell channels as:
  - lc_ch0_N: input/start-side tension
  - lc_ch1_N: output/end-side tension

Use raw mode to compare absolute initial-tension operating points, and
relative mode to compare whether the loop shape remains similar after
subtracting each run's initial tension.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


def _float_or_nan(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def read_tension_csv(path: Path, start_s: float | None, end_s: float | None, force_mode: str):
    times: list[float] = []
    tin: list[float] = []
    tout: list[float] = []

    with path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        required = {"time_s", "lc_ch0_N", "lc_ch1_N"}
        missing = sorted(required - fieldnames)
        if missing:
            raise ValueError(f"{path}: missing CSV columns: {', '.join(missing)}")

        use_abs_cols = force_mode == "abs" and {"lc_ch0_abs_N", "lc_ch1_abs_N"}.issubset(fieldnames)
        for row in reader:
            t = _float_or_nan(row.get("time_s", ""))
            if use_abs_cols:
                ch0 = _float_or_nan(row.get("lc_ch0_abs_N", ""))
                ch1 = _float_or_nan(row.get("lc_ch1_abs_N", ""))
            else:
                ch0 = _float_or_nan(row.get("lc_ch0_N", ""))
                ch1 = _float_or_nan(row.get("lc_ch1_N", ""))
            if math.isnan(t) or math.isnan(ch0) or math.isnan(ch1):
                continue
            if force_mode == "abs" and not use_abs_cols:
                ch0 = abs(ch0)
                ch1 = abs(ch1)
            if start_s is not None and t < start_s:
                continue
            if end_s is not None and t > end_s:
                continue
            times.append(t)
            tin.append(ch0)
            tout.append(ch1)

    if not tin:
        raise ValueError(f"{path}: no valid tension samples found")
    return times, tin, tout


def mean(values: list[float]) -> float:
    return sum(values) / max(1, len(values))


def subtract_baseline(values: list[float], baseline_samples: int) -> tuple[list[float], float]:
    n = max(1, min(baseline_samples, len(values)))
    baseline = mean(values[:n])
    return [v - baseline for v in values], baseline


def loop_area(x: list[float], y: list[float]) -> float:
    if len(x) < 3:
        return 0.0
    area = 0.0
    for i in range(len(x)):
        j = (i + 1) % len(x)
        area += x[i] * y[j] - x[j] * y[i]
    return 0.5 * abs(area)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot raw and/or relative tension hysteresis loops from EPOS CSV logs."
    )
    parser.add_argument("csv", nargs="+", type=Path, help="CSV log file(s)")
    parser.add_argument(
        "--mode",
        choices=("raw", "relative", "both"),
        default="both",
        help="raw uses absolute tension; relative subtracts each file's initial baseline",
    )
    parser.add_argument(
        "--force-mode",
        choices=("abs", "signed"),
        default="abs",
        help="abs plots tension magnitude |F|; signed preserves load-cell sign",
    )
    parser.add_argument("--start", type=float, default=None, help="start time in seconds")
    parser.add_argument("--end", type=float, default=None, help="end time in seconds")
    parser.add_argument(
        "--baseline-samples",
        type=int,
        default=200,
        help="samples used for relative-mode initial tension baseline",
    )
    parser.add_argument("--labels", nargs="*", default=None, help="optional labels for CSV files")
    parser.add_argument("--title", default="Tension Hysteresis Loop")
    parser.add_argument("--out", type=Path, default=None, help="save figure to this path")
    parser.add_argument("--show", action="store_true", help="show an interactive window")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit("matplotlib is required: python3 -m pip install matplotlib") from exc

    labels = args.labels or [p.stem for p in args.csv]
    if len(labels) != len(args.csv):
        raise SystemExit("--labels count must match the number of CSV files")

    if args.mode == "both":
        fig, axes = plt.subplots(1, 2, figsize=(11, 5), constrained_layout=True)
        plot_modes = ["raw", "relative"]
    else:
        fig, ax = plt.subplots(1, 1, figsize=(6, 5), constrained_layout=True)
        axes = [ax]
        plot_modes = [args.mode]

    summaries: list[str] = []
    for path, label in zip(args.csv, labels):
        _, tin_raw, tout_raw = read_tension_csv(path, args.start, args.end, args.force_mode)
        tin_rel, tin0 = subtract_baseline(tin_raw, args.baseline_samples)
        tout_rel, tout0 = subtract_baseline(tout_raw, args.baseline_samples)

        for ax, mode in zip(axes, plot_modes):
            if mode == "raw":
                x, y = tin_raw, tout_raw
                if args.force_mode == "abs":
                    xlabel, ylabel = "|T_in| [N]", "|T_out| [N]"
                else:
                    xlabel, ylabel = "T_in [N]", "T_out [N]"
            else:
                x, y = tin_rel, tout_rel
                if args.force_mode == "abs":
                    xlabel, ylabel = "Delta |T_in| [N]", "Delta |T_out| [N]"
                else:
                    xlabel, ylabel = "Delta T_in [N]", "Delta T_out [N]"
            ax.plot(x, y, linewidth=1.2, label=label)
            ax.set_xlabel(xlabel)
            ax.set_ylabel(ylabel)
            ax.grid(True, alpha=0.3)
            ax.axis("equal")

        summaries.append(
            f"{label}: Tin0={tin0:.3f} N, Tout0={tout0:.3f} N, "
            f"raw_area={loop_area(tin_raw, tout_raw):.4f}, "
            f"relative_area={loop_area(tin_rel, tout_rel):.4f}"
        )

    for ax, mode in zip(axes, plot_modes):
        ax.set_title(f"{args.title} ({mode})")
        ax.legend()

    print("\n".join(summaries))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(args.out, dpi=180)
        print(f"saved: {args.out}")

    if args.show or not args.out:
        plt.show()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
