from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, quoteattr

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIRECTORY = REPOSITORY_ROOT / "docs" / "user" / "assets"
CHART_STEM = "benchmark-latency"
ALT_TEXT_DOCUMENTS = (
    REPOSITORY_ROOT / "README.md",
    REPOSITORY_ROOT / "docs" / "user" / "benchmarks" / "index.md",
)
LOCAL_WORKLOAD = "read_heavy-small"
REAL_SERVER_LOG_PATTERN = re.compile(
    r"Median read latency over \d+ measured reads per phase: "
    r"cached [\d.]+ microseconds, direct (?P<direct>[\d.]+) microseconds"
)
UNITS = {
    -9: ("ns", "nanoseconds"),
    -6: ("\N{MICRO SIGN}s", "microseconds"),
    -3: ("ms", "milliseconds"),
    0: ("s", "seconds"),
}

FONT_FAMILY = "-apple-system,Segoe UI,Helvetica,Arial,sans-serif"
WIDTH = 700
LABEL_X = 16
PLOT_LEFT = 245
PLOT_WIDTH = 360
FIRST_BAR_TOP = 70
ROW_PITCH = 55
BAR_HEIGHT = 28
BAR_RADIUS = 4
VALUE_LABEL_GAP = 14
MINIMUM_DECADES_BELOW_SMALLEST_BAR = 0.1
TITLE = "Illustrative read latency"
FOOTER = "Medians · cached read measured on a busy CPU · log-scaled axis"


@dataclass(frozen=True, slots=True)
class Theme:
    name: str
    surface: str
    ink: str
    muted_ink: str
    rule: str
    direct: str
    cached: str


THEMES = (
    Theme("light", "#fcfcfb", "#0b0b0b", "#52514e", "#d8d7d2", "#2a78d6", "#eb6834"),
    Theme("dark", "#1a1a19", "#f0efec", "#c3c2b7", "#383835", "#3987e5", "#d95926"),
)


@dataclass(frozen=True, slots=True)
class Bar:
    label: str
    seconds: float
    cached: bool


@dataclass(frozen=True, slots=True)
class Measurements:
    local_direct_seconds: float
    remote_deployment: str
    remote_direct_seconds: float
    cached_seconds: float

    def bars(self) -> tuple[Bar, ...]:
        return (
            Bar("Direct read — local server", self.local_direct_seconds, cached=False),
            Bar(
                f"Direct read — {self.remote_deployment}",
                self.remote_direct_seconds,
                cached=False,
            ),
            Bar("Cached read — either one", self.cached_seconds, cached=True),
        )


def _local_direct_p50_seconds(report: dict[str, Any], report_path: Path) -> float:
    for variant in report["measurement"]["variants"]:
        if variant["name"] != "raw":
            continue
        for row in variant["by_outcome"]:
            if row["operation"] == "read" and row["outcome"] == "raw":
                return float(row["p50_seconds"])
    message = f"{report_path}: no direct read p50"
    raise SystemExit(message)


def load_measurements(
    local_report_path: Path,
    real_server_log_path: Path,
    remote_deployment: str,
    cached_hit_report_path: Path,
) -> Measurements:
    report = json.loads(local_report_path.read_text(encoding="utf-8"))
    workload_name = report["workload"]["name"]
    if workload_name != LOCAL_WORKLOAD:
        message = (
            f"{local_report_path}: expected the {LOCAL_WORKLOAD} workload, "
            f"found {workload_name}"
        )
        raise SystemExit(message)
    matches = list(
        REAL_SERVER_LOG_PATTERN.finditer(
            real_server_log_path.read_text(encoding="utf-8")
        )
    )
    if not matches:
        message = (
            f"{real_server_log_path}: no real-server median read latency; "
            "run the real-server benchmark with REAL_MONGODB_URI configured"
        )
        raise SystemExit(message)
    cached_hit_report = json.loads(cached_hit_report_path.read_text(encoding="utf-8"))
    return Measurements(
        local_direct_seconds=_local_direct_p50_seconds(report, local_report_path),
        remote_deployment=remote_deployment,
        remote_direct_seconds=float(matches[-1]["direct"]) / 1e6,
        cached_seconds=float(cached_hit_report["median_hit_seconds"]),
    )


def _unit_exponent(seconds: float) -> int:
    return 3 * math.floor(math.log10(seconds) / 3)


def _format_duration(seconds: float, *, spoken: bool) -> str:
    rounded = float(f"{seconds:.3g}")
    exponent = _unit_exponent(rounded)
    symbol, word = UNITS[exponent]
    value = f"{rounded / 10**exponent:.3g}"
    return f"{value} {word}" if spoken else f"{value} {symbol}"


def _tick_label(decade: int) -> str:
    exponent = _unit_exponent(10.0**decade)
    return f"{10 ** (decade - exponent)}{UNITS[exponent][0]}"


def alt_text(measurements: Measurements) -> str:
    def spoken(seconds: float) -> str:
        return _format_duration(seconds, spoken=True)

    return (
        f"{TITLE} on a logarithmic scale: direct local MongoDB read, "
        f"{spoken(measurements.local_direct_seconds)}; direct "
        f"{measurements.remote_deployment} read, "
        f"{spoken(measurements.remote_direct_seconds)}; cached read in either "
        f"deployment, {spoken(measurements.cached_seconds)}."
    )


@dataclass(frozen=True, slots=True)
class PlacedBar:
    bar: Bar
    top: float
    right: float
    value_label: str


@dataclass(frozen=True, slots=True)
class Layout:
    alt: str
    bars: tuple[PlacedBar, ...]
    ticks: tuple[tuple[float, str], ...]
    axis_y: float
    height: float


def build_layout(measurements: Measurements) -> Layout:
    bars = measurements.bars()
    smallest = min(bar.seconds for bar in bars)
    largest = max(bar.seconds for bar in bars)
    first_decade = math.floor(math.log10(smallest) - MINIMUM_DECADES_BELOW_SMALLEST_BAR)
    last_decade = math.ceil(math.log10(largest))
    pixels_per_decade = PLOT_WIDTH / (last_decade - first_decade)
    axis_y = FIRST_BAR_TOP + ROW_PITCH * len(bars) - 15
    return Layout(
        alt=alt_text(measurements),
        bars=tuple(
            PlacedBar(
                bar=bar,
                top=FIRST_BAR_TOP + ROW_PITCH * index,
                right=PLOT_LEFT
                + (math.log10(bar.seconds) - first_decade) * pixels_per_decade,
                value_label=_format_duration(bar.seconds, spoken=False),
            )
            for index, bar in enumerate(bars)
        ),
        ticks=tuple(
            (
                round(PLOT_LEFT + (decade - first_decade) * pixels_per_decade, 2),
                _tick_label(decade),
            )
            for decade in range(first_decade, last_decade + 1)
        ),
        axis_y=axis_y,
        height=axis_y + 60,
    )


def _text(
    x: float, y: float, content: str, *, size: int, fill: str, extra: str = ""
) -> str:
    return (
        f'  <text x="{x:g}" y="{y:g}"{extra} font-family="{FONT_FAMILY}" '
        f'font-size="{size}" fill="{fill}">{escape(content)}</text>'
    )


def _line(x1: float, y1: float, x2: float, y2: float, stroke: str) -> str:
    return (
        f'  <line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" '
        f'stroke="{stroke}" stroke-width="1"/>'
    )


def _bar_path(top: float, right: float, fill: str) -> str:
    bottom = top + BAR_HEIGHT
    radius = min(BAR_RADIUS, (right - PLOT_LEFT) / 2)
    inner = right - radius
    return (
        f'  <path d="M{PLOT_LEFT},{top:g} L{inner:.2f},{top:g} '
        f"Q{right:.2f},{top:g} {right:.2f},{top + radius:g} "
        f"L{right:.2f},{bottom - radius:g} "
        f"Q{right:.2f},{bottom:g} {inner:.2f},{bottom:g} "
        f'L{PLOT_LEFT},{bottom:g} Z" fill="{fill}"/>'
    )


def render_svg(layout: Layout, theme: Theme) -> str:
    axis_y = layout.axis_y
    elements = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {WIDTH} {layout.height}" width="{WIDTH}" '
            f'height="{layout.height}" role="img" aria-label={quoteattr(layout.alt)}>'
        ),
        (
            f'  <rect x="0" y="0" width="{WIDTH}" height="{layout.height}" '
            f'fill="{theme.surface}" rx="8"/>'
        ),
        _text(LABEL_X, 32, TITLE, size=20, fill=theme.ink, extra=' font-weight="600"'),
        _line(PLOT_LEFT, 55, PLOT_LEFT, axis_y, theme.rule),
    ]
    for placed in layout.bars:
        baseline = placed.top + 19
        fill = theme.cached if placed.bar.cached else theme.direct
        elements.extend(
            (
                _text(LABEL_X, baseline, placed.bar.label, size=15, fill=theme.ink),
                _bar_path(placed.top, placed.right, fill),
                _text(
                    round(placed.right + VALUE_LABEL_GAP, 2),
                    baseline,
                    placed.value_label,
                    size=15,
                    fill=theme.ink,
                    extra=' font-weight="600"',
                ),
            )
        )
    elements.append(
        _line(PLOT_LEFT, axis_y, PLOT_LEFT + PLOT_WIDTH, axis_y, theme.rule)
    )
    for tick_x, label in layout.ticks:
        elements.extend(
            (
                _line(tick_x, axis_y, tick_x, axis_y + 6, theme.rule),
                _text(
                    tick_x,
                    axis_y + 20,
                    label,
                    size=12,
                    fill=theme.muted_ink,
                    extra=' text-anchor="middle"',
                ),
            )
        )
    elements.extend(
        (_text(LABEL_X, axis_y + 46, FOOTER, size=13, fill=theme.muted_ink), "</svg>")
    )
    return "\n".join(elements) + "\n"


def _replace_alt_text(document: Path, alt: str) -> None:
    content = document.read_text(encoding="utf-8")
    markdown_image = re.compile(
        rf"!\[[^\]]*\](?=\([^)]*{CHART_STEM}-(?:light|dark)\.svg)"
    )
    updated, count = markdown_image.subn(lambda _: f"![{alt}]", content)
    if count == 0:
        message = f"{document}: no {CHART_STEM} image reference found"
        raise SystemExit(message)
    document.write_text(updated, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render the light and dark illustrative read-latency charts."
    )
    parser.add_argument("--local-report", type=Path, required=True)
    parser.add_argument("--real-server-log", type=Path, required=True)
    parser.add_argument("--remote-deployment", required=True)
    parser.add_argument("--cached-hit-report", type=Path, required=True)
    arguments = parser.parse_args()
    layout = build_layout(
        load_measurements(
            arguments.local_report,
            arguments.real_server_log,
            arguments.remote_deployment,
            arguments.cached_hit_report,
        )
    )
    for theme in THEMES:
        output = ASSETS_DIRECTORY / f"{CHART_STEM}-{theme.name}.svg"
        output.write_text(render_svg(layout, theme), encoding="utf-8")
    for document in ALT_TEXT_DOCUMENTS:
        _replace_alt_text(document, layout.alt)
    print(layout.alt)


if __name__ == "__main__":
    main()
