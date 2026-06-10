#!/usr/bin/env python3
"""
generate_ossm_results.py

Reads evaluation CSV+JSON pairs from ossm/results/ (including mcp/ and no-mcp/
subfolders) and generates:
  - RESULTS_OSSM.md — OSSM summary for OpenShift LightSpeed reporting
  - ossm/results/<variant>/<conv>_<model>.md — per-run detail pages

Current scope: OpenAI provider, conversations tagged check_mesh_Status (MCP)
and no_kiali (without MCP), metric custom:answer_correctness.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from generate_results import (
    ConvRun,
    detail_page_path,
    generate_detail_md,
    load_scenarios,
    result_emoji,
)

OSSM_METRIC = "custom:answer_correctness"
OSSM_PROVIDER = "openai"
OSSM_VARIANTS = ("mcp", "no-mcp")
VARIANT_LABELS = {
    "mcp": "With MCP (`check_mesh_Status`)",
    "no-mcp": "Without MCP (`no_kiali`)",
    "legacy": "Legacy (flat results/)",
}


def _json_for_csv(csv_path: Path) -> Path | None:
    """Prefer summary JSON next to the CSV (supports nested variant dirs)."""
    sibling = csv_path.with_name(
        csv_path.name.replace("_detailed.csv", "_summary.json")
    )
    return sibling if sibling.is_file() else None


def _variant_for(csv_path: Path, results_dir: Path) -> str:
    try:
        rel = csv_path.parent.relative_to(results_dir.resolve())
    except ValueError:
        return "legacy"
    if rel.parts and rel.parts[0] in OSSM_VARIANTS:
        return rel.parts[0]
    return "legacy"


def _csv_paths_for_root(variant: str, root: Path) -> list[Path]:
    if variant == "legacy":
        return sorted(root.glob("evaluation_*_detailed.csv"), reverse=True)
    return sorted(root.rglob("evaluation_*_detailed.csv"), reverse=True)


def find_all_ossm_runs(results_dir: Path) -> list[tuple[str, ConvRun]]:
    """Find latest run per (variant, conversation, model) under mcp/ and no-mcp/."""
    results_dir = results_dir.resolve()
    seen: set[tuple[str, str, str]] = set()
    runs: list[tuple[str, ConvRun]] = []

    search_roots: list[tuple[str, Path]] = []
    for variant in OSSM_VARIANTS:
        sub = results_dir / variant
        if sub.is_dir():
            search_roots.append((variant, sub))
    if not search_roots:
        search_roots.append(("legacy", results_dir))

    for variant, root in search_roots:
        for csv_path in _csv_paths_for_root(variant, root):
            if variant == "legacy" and csv_path.parent != root:
                continue
            json_path = _json_for_csv(csv_path)
            if not json_path:
                continue
            run = ConvRun(csv_path, json_path)
            detected = _variant_for(csv_path, results_dir)
            key = (detected, run.gid, run.api_model)
            if key in seen:
                continue
            seen.add(key)
            runs.append((detected, run))
            print(f"  found: {detected}/{run.gid} ({run.api_model}) — {csv_path.name}")

    return sorted(runs, key=lambda item: (item[0], item[1].gid))


def _rel_link(path: Path, output: Path) -> str:
    return str(path.resolve().relative_to(output.resolve().parent))


def _summary_row(variant: str, run: ConvRun, output: Path) -> str:
    o = run.overall
    tot = o.get("TOTAL", 0)
    p = o.get("PASS", 0)
    f = o.get("FAIL", 0)
    e = o.get("ERROR", 0)
    rate = f"{p / tot * 100:.0f}%" if tot else "—"
    icon = "✅" if f + e == 0 else ("❌" if p == 0 else "🟡")
    metric_stats = (
        run.summary.get("summary_stats", {})
        .get("by_metric", {})
        .get(OSSM_METRIC, {})
    )
    mean = metric_stats.get("score_statistics", {}).get("mean", "")
    mean_str = f"{float(mean):.2f}" if mean != "" else "—"
    detail = _rel_link(detail_page_path(run), output)
    variant_label = VARIANT_LABELS.get(variant, variant)
    return (
        f"| {variant_label} | [`{run.gid}`]({detail}) | `{run.model_label}` | "
        f"{p} | {f} | {e} | {icon} {rate} | {mean_str} |"
    )


def generate_ossm_summary_md(
    runs: list[tuple[str, ConvRun]],
    scenarios: dict,
    output: Path,
) -> None:
    """Build RESULTS_OSSM.md — summary grouped by MCP variant."""
    if not runs:
        raise ValueError("No runs to summarize")

    all_gids = sorted({run.gid for _, run in runs})
    rep = runs[0][1]
    latest_ts = max(run.timestamp for _, run in runs)

    lines: list[str] = [
        "# OSSM Evaluation Results",
        "",
        "Evaluation results for the **OpenShift LightSpeed (OLS) OSSM** test suite.",
        "",
        f"**Latest run:** {latest_ts} &nbsp;|&nbsp; "
        f"**Provider:** `{OSSM_PROVIDER}` &nbsp;|&nbsp; "
        f"**Metric:** `{OSSM_METRIC}`",
        "",
        f"**OLS backend:** `{rep.api_provider}/{rep.api_model}` &nbsp;|&nbsp; "
        f"**Judge:** `{rep.llm_provider}/{rep.llm_model}`",
        "",
        "See [OSSM.md](OSSM.md) for how to run these tests and refresh this report.",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| Variant | Conversation | OLS Model | ✅ Pass | ❌ Fail | ⚠️ Error | Pass Rate | Mean Score |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for variant, run in runs:
        lines.append(_summary_row(variant, run, output))

    lines += ["", "## Metric Result", ""]
    lines += [
        "| Variant | Metric | Conversation | Result | Score |",
        "|---|---|---|---|---|",
    ]
    for variant, run in runs:
        row = next(
            (
                r
                for r in run.rows
                if r.get("metric_identifier") == OSSM_METRIC
                and r.get("conversation_group_id") == run.gid
            ),
            None,
        )
        if not row:
            continue
        score = row.get("score", "")
        try:
            score_str = f"{float(score):.2f}"
        except (ValueError, TypeError):
            score_str = "—"
        variant_label = VARIANT_LABELS.get(variant, variant)
        lines.append(
            f"| {variant_label} | `{OSSM_METRIC}` | `{run.gid}` | "
            f"{result_emoji(row.get('result', ''))} {row.get('result', '')} | {score_str} |"
        )

    lines += ["", "## Scenario Detail Pages", ""]
    for gid in all_gids:
        desc = scenarios.get(gid, {}).get("_description", "")
        desc_str = f" — {desc}" if desc else ""
        lines.append(f"### `{gid}`{desc_str}")
        lines.append("")
        for variant, run in runs:
            if run.gid != gid:
                continue
            detail = _rel_link(detail_page_path(run), output)
            o = run.overall
            p, tot = o.get("PASS", 0), o.get("TOTAL", 0)
            rate = f"{p / tot * 100:.0f}%" if tot else "—"
            icon = "✅" if o.get("FAIL", 0) + o.get("ERROR", 0) == 0 else "❌"
            variant_label = VARIANT_LABELS.get(variant, variant)
            lines.append(
                f"- [{icon} {variant_label} / `{run.model_label}` — "
                f"{rate} ({p}/{tot})]({detail}) — {run.timestamp}"
            )
        lines.append("")

    # Graphs — one pass_rates (or status_breakdown) per variant
    graph_lines: list[str] = []
    for variant in OSSM_VARIANTS + ("legacy",):
        variant_runs = [(v, r) for v, r in runs if v == variant]
        if not variant_runs:
            continue
        latest = max(variant_runs, key=lambda item: item[1].timestamp)[1]
        graphs = latest.graphs
        primary = next(
            (k for k in ("pass_rates", "status_breakdown", "score_distribution") if k in graphs),
            None,
        )
        if not primary:
            continue
        g = graphs[primary]
        label = primary.replace("_", " ").title()
        rel = _rel_link(g, output)
        variant_label = VARIANT_LABELS.get(variant, variant)
        graph_lines += [
            f"### {variant_label}",
            "",
            f"![{label} — {latest.gid}]({rel})",
            "",
        ]

    if graph_lines:
        lines += ["---", "", "## Graphs", ""] + graph_lines

    lines.append("*Generated by `scripts/generate_ossm_results.py`*")
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ RESULTS_OSSM.md written to {output}")


def main() -> None:
    root = Path(__file__).parent.parent
    parser = argparse.ArgumentParser(
        description="Generate RESULTS_OSSM.md from ossm/results evaluation output"
    )
    parser.add_argument(
        "--results-dir",
        default=str(root / "ossm" / "results"),
        help="Root directory (scans mcp/ and no-mcp/ subfolders when present)",
    )
    parser.add_argument(
        "--scenarios-file",
        default=str(root / "ossm" / "conversations.yaml"),
        help="OSSM conversations YAML for scenario metadata",
    )
    parser.add_argument(
        "--output",
        default=str(root / "RESULTS_OSSM.md"),
        help="Output path for the OSSM summary report",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    scenarios_file = Path(args.scenarios_file)
    output = Path(args.output)

    if not results_dir.exists():
        print(f"ERROR: Results directory not found: {results_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {results_dir} (variants: {', '.join(OSSM_VARIANTS)})...")
    runs = find_all_ossm_runs(results_dir)
    if not runs:
        print(
            f"ERROR: No CSV/JSON pairs found under {results_dir}/{{mcp,no-mcp}}/",
            file=sys.stderr,
        )
        sys.exit(1)

    for _, run in runs:
        if run.api_provider != OSSM_PROVIDER:
            print(
                f"  warning: unexpected provider {run.api_provider!r} "
                f"(OSSM suite expects {OSSM_PROVIDER!r})",
                file=sys.stderr,
            )

    scenarios = load_scenarios(scenarios_file)

    print("Generating OSSM detail pages:")
    for variant, run in runs:
        sc = scenarios.get(run.gid, {})
        out = detail_page_path(run)
        generate_detail_md(run, sc, out)
        print(f"  ✓ [{variant}] {out.relative_to(root)}")

    generate_ossm_summary_md(runs, scenarios, output)


if __name__ == "__main__":
    main()
