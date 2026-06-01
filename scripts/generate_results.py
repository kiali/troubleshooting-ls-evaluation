#!/usr/bin/env python3
"""
generate_results.py

Reads the latest evaluation output from results/ and generates RESULTS.md
in the project root. Correlates CSV/JSON results with scenario_evals.yaml
to show queries, expected responses, and actual scores side by side.

Usage:
    python scripts/generate_results.py
    python scripts/generate_results.py --results-dir results --output RESULTS.md
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_latest_run(results_dir: Path) -> tuple[Path, Path]:
    """Return (csv_path, json_path) for the most recent evaluation run."""
    csvs = sorted(results_dir.glob("evaluation_*_detailed.csv"), reverse=True)
    jsons = sorted(results_dir.glob("evaluation_*_summary.json"), reverse=True)
    if not csvs or not jsons:
        print(f"ERROR: No evaluation results found in {results_dir}", file=sys.stderr)
        sys.exit(1)
    return csvs[0], jsons[0]


def extract_timestamp(path: Path) -> str:
    """Turn 'evaluation_20260601_101035_detailed.csv' into '2026-06-01 10:10:35'."""
    m = re.search(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", path.name)
    if m:
        y, mo, d, h, mi, s = m.groups()
        return f"{y}-{mo}-{d} {h}:{mi}:{s}"
    return path.name


def find_graphs(results_dir: Path, csv_path: Path) -> list[Path]:
    """Find all PNG graphs belonging to this run, sorted by name."""
    stem = re.search(r"(evaluation_\d+_\d+)", csv_path.name)
    prefix = stem.group(1) if stem else "evaluation_"
    graphs_dir = results_dir / "graphs"
    return sorted(graphs_dir.glob(f"{prefix}*.png"))


def load_scenarios(scenario_file: Path) -> dict:
    """
    Load scenario_evals.yaml and return a nested dict:
        {conversation_group_id: {turn_id: {query, expected_response, description}}}
    """
    scenarios: dict = {}
    if not scenario_file.exists():
        return scenarios
    with scenario_file.open() as f:
        docs = yaml.safe_load(f)
    if not docs:
        return scenarios
    for conv in docs:
        gid = conv.get("conversation_group_id", "")
        scenarios[gid] = {
            "_description": conv.get("description", ""),
            "_tag": conv.get("tag", ""),
        }
        for turn in conv.get("turns", []):
            tid = turn.get("turn_id", "")
            scenarios[gid][tid] = {
                "query": (turn.get("query") or "").strip(),
                "expected_response": (turn.get("expected_response") or "").strip(),
                "turn_metrics": turn.get("turn_metrics", []),
            }
    return scenarios


def load_csv(csv_path: Path) -> list[dict]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_json(json_path: Path) -> dict:
    with json_path.open(encoding="utf-8") as f:
        return json.load(f)


def result_emoji(result: str) -> str:
    return {"PASS": "✅", "FAIL": "❌", "ERROR": "⚠️", "SKIPPED": "⏭️"}.get(result, result)


def score_bar(score: str, width: int = 20) -> str:
    """Simple ASCII progress bar for a 0–1 score."""
    try:
        v = float(score)
    except (ValueError, TypeError):
        return ""
    filled = round(v * width)
    return f"`{'█' * filled}{'░' * (width - filled)}` {v:.2f}"


# ── Markdown generation ───────────────────────────────────────────────────────

def generate_md(
    csv_path: Path,
    json_path: Path,
    graphs: list[Path],
    scenarios: dict,
    output: Path,
    results_dir: Path,
) -> None:
    summary = load_json(json_path)
    rows = load_csv(csv_path)
    timestamp = extract_timestamp(csv_path)

    overall = summary.get("summary_stats", {}).get("overall", {})
    by_metric = summary.get("summary_stats", {}).get("by_metric", {})
    by_conv = summary.get("summary_stats", {}).get("by_conversation", {})
    latency = summary.get("summary_stats", {}).get("agent_latency_stats", {})

    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────────
    lines += [
        "# Evaluation Results",
        "",
        f"**Run:** {timestamp}  ",
        f"**Conversations:** {len(by_conv)}  ",
        f"**Total evaluations:** {overall.get('TOTAL', 0)}  ",
        "",
        "---",
        "",
    ]

    # ── Overall summary ───────────────────────────────────────────────────────
    lines += [
        "## Overall Summary",
        "",
        "| | Count | Rate |",
        "|---|---|---|",
        f"| {result_emoji('PASS')} Pass   | {overall.get('PASS', 0)} | {overall.get('pass_rate', 0):.1f}% |",
        f"| {result_emoji('FAIL')} Fail   | {overall.get('FAIL', 0)} | {overall.get('fail_rate', 0):.1f}% |",
        f"| {result_emoji('ERROR')} Error  | {overall.get('ERROR', 0)} | {overall.get('error_rate', 0):.1f}% |",
        f"| {result_emoji('SKIPPED')} Skipped | {overall.get('SKIPPED', 0)} | {overall.get('skipped_rate', 0):.1f}% |",
        "",
    ]

    # Token usage
    lines += [
        "### Token Usage",
        "",
        "| | Tokens |",
        "|---|---|",
        f"| Judge LLM (input) | {overall.get('total_judge_llm_input_tokens', 0):,} |",
        f"| Judge LLM (output) | {overall.get('total_judge_llm_output_tokens', 0):,} |",
        f"| API (input) | {overall.get('total_api_input_tokens', 0):,} |",
        f"| API (output) | {overall.get('total_api_output_tokens', 0):,} |",
        f"| **Total** | **{overall.get('total_tokens', 0):,}** |",
        "",
    ]

    # Agent latency
    if latency:
        lines += [
            "### Agent Latency",
            "",
            "| | Seconds |",
            "|---|---|",
            f"| Mean | {latency.get('mean', 0):.2f}s |",
            f"| Median | {latency.get('median', 0):.2f}s |",
            f"| Min | {latency.get('min', 0):.2f}s |",
            f"| Max | {latency.get('max', 0):.2f}s |",
            f"| p95 | {latency.get('p95', 0):.2f}s |",
            "",
        ]

    # ── By metric ─────────────────────────────────────────────────────────────
    lines += ["## Results by Metric", ""]
    lines += ["| Metric | Pass | Fail | Error | Pass Rate | Mean Score |"]
    lines += ["|--------|------|------|-------|-----------|------------|"]
    for metric, stats in by_metric.items():
        mean = stats.get("score_statistics", {}).get("mean", "")
        mean_str = f"{float(mean):.2f}" if mean != "" else "—"
        lines.append(
            f"| `{metric}` | {stats.get('pass',0)} | {stats.get('fail',0)} | "
            f"{stats.get('error',0)} | {stats.get('pass_rate',0):.1f}% | {mean_str} |"
        )
    lines.append("")

    # ── Graphs ────────────────────────────────────────────────────────────────
    if graphs:
        lines += ["## Graphs", ""]
        for g in graphs:
            # Use a relative path from the output file location (project root)
            rel = g.relative_to(output.parent)
            label = g.stem.replace(re.search(r"evaluation_\d+_\d+_?", g.stem).group(), "").replace("_", " ").strip().title()
            lines += [f"### {label}", "", f"![{label}]({rel})", ""]

    # ── Per-scenario details ───────────────────────────────────────────────────
    lines += ["## Scenario Results", ""]

    # Group CSV rows by conversation
    convs: dict = {}
    for row in rows:
        gid = row.get("conversation_group_id", "")
        convs.setdefault(gid, []).append(row)

    for gid, conv_rows in convs.items():
        sc = scenarios.get(gid, {})
        desc = sc.get("_description", "")
        conv_stats = by_conv.get(gid, {})

        pass_rate = conv_stats.get("pass_rate", 0)
        total_c = conv_stats.get("pass", 0) + conv_stats.get("fail", 0) + conv_stats.get("error", 0)

        lines += [
            f"### `{gid}`",
            "",
        ]
        if desc:
            lines += [f"> {desc}", ""]

        lines += [
            f"**Pass rate:** {pass_rate:.1f}% ({conv_stats.get('pass',0)}/{total_c})",
            "",
        ]

        # Group by turn (a conversation may have multiple metrics per turn)
        turns: dict = {}
        for row in conv_rows:
            tid = row.get("turn_id", "")
            turns.setdefault(tid, []).append(row)

        for tid, turn_rows in turns.items():
            turn_sc = sc.get(tid, {})
            query = turn_sc.get("query", "")
            expected = turn_sc.get("expected_response", "")

            # Use first row for common fields
            first = turn_rows[0]
            response = first.get("response", "").strip()

            lines += [f"#### Turn: `{tid}`", ""]

            if query:
                lines += [f"**Query:** {query}", ""]
            if expected:
                lines += ["<details>", "<summary>Expected response</summary>", "", expected, "", "</details>", ""]

            # Metrics table
            lines += ["| Metric | Result | Score |", "|--------|--------|-------|"]
            for row in turn_rows:
                metric = row.get("metric_identifier", "")
                result = row.get("result", "")
                score = row.get("score", "")
                lines.append(
                    f"| `{metric}` | {result_emoji(result)} {result} | {score_bar(score)} |"
                )
            lines.append("")

            # Reasons
            for row in turn_rows:
                reason = row.get("reason", "").strip()
                if reason:
                    lines += [
                        "<details>",
                        f"<summary>Judge reason — {row.get('metric_identifier','')}</summary>",
                        "",
                        reason,
                        "",
                        "</details>",
                        "",
                    ]

            # Response (truncated)
            if response:
                truncated = response[:600] + ("…" if len(response) > 600 else "")
                lines += [
                    "<details>",
                    "<summary>Agent response (truncated)</summary>",
                    "",
                    "```",
                    truncated,
                    "```",
                    "",
                    "</details>",
                    "",
                ]

        lines.append("---")
        lines.append("")

    # ── Footer ────────────────────────────────────────────────────────────────
    lines += [
        f"*Generated from `{csv_path.name}` and `{json_path.name}`.*",
    ]

    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ RESULTS.md written to {output}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    root = Path(__file__).parent.parent

    parser = argparse.ArgumentParser(description="Generate RESULTS.md from evaluation output")
    parser.add_argument("--results-dir", default=str(root / "results"), help="Path to results/ directory")
    parser.add_argument("--scenarios", default=str(root / "scenario_evals.yaml"), help="Path to scenario_evals.yaml")
    parser.add_argument("--output", default=str(root / "RESULTS.md"), help="Output Markdown file")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    scenario_file = Path(args.scenarios)
    output = Path(args.output)

    csv_path, json_path = find_latest_run(results_dir)
    print(f"Using: {csv_path.name}")
    print(f"Using: {json_path.name}")

    graphs = find_graphs(results_dir, csv_path)
    scenarios = load_scenarios(scenario_file)
    generate_md(csv_path, json_path, graphs, scenarios, output, results_dir)


if __name__ == "__main__":
    main()
