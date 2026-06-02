#!/usr/bin/env python3
"""
generate_results.py

Reads the latest evaluation output from results/ and generates RESULTS.md
in the project root. Correlates CSV/JSON results with scenario_evals.yaml
to show queries, expected responses, tool calls, keywords, and actual scores.

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
    """
    Find the latest CSV/JSON pair. Searches:
      1. results/<scenario>/evaluation_*.csv   (per-scenario subdirs from make all)
      2. results/evaluation_*.csv              (flat layout from individual targets)
    Returns the most recent pair across all locations.
    """
    csvs = sorted(results_dir.rglob("evaluation_*_detailed.csv"), reverse=True)
    jsons = sorted(results_dir.rglob("evaluation_*_summary.json"), reverse=True)
    if not csvs or not jsons:
        print(f"ERROR: No evaluation results found under {results_dir}", file=sys.stderr)
        sys.exit(1)
    # Pair by matching timestamp prefix
    latest_csv = csvs[0]
    stem = re.search(r"(evaluation_\d+_\d+)", latest_csv.name)
    prefix = stem.group(1) if stem else ""
    paired_json = next(
        (j for j in jsons if prefix and prefix in j.name),
        jsons[0],
    )
    return latest_csv, paired_json


def find_all_runs(results_dir: Path) -> list[tuple[str, Path, Path]]:
    """
    Return all (scenario_name, csv, json) tuples.

    Layout A — per-scenario subdirs (make <scenario> targets):
        results/<name>/evaluation_*_detailed.csv

    Layout B — flat (make all with conversations.yaml):
        results/evaluation_*_detailed.csv
        → returned as ("", csv, json) — no subdir name needed
    """
    pairs: list[tuple[str, Path, Path]] = []

    for subdir in sorted(results_dir.iterdir()):
        if not subdir.is_dir() or subdir.name == "graphs":
            continue
        csvs = sorted(subdir.glob("evaluation_*_detailed.csv"), reverse=True)
        jsons = sorted(subdir.glob("evaluation_*_summary.json"), reverse=True)
        if csvs and jsons:
            pairs.append((subdir.name, csvs[0], jsons[0]))

    # Flat fallback — all conversations in one run
    if not pairs:
        csvs = sorted(results_dir.glob("evaluation_*_detailed.csv"), reverse=True)
        jsons = sorted(results_dir.glob("evaluation_*_summary.json"), reverse=True)
        if csvs and jsons:
            pairs.append(("", csvs[0], jsons[0]))

    return pairs


def extract_timestamp(path: Path) -> str:
    m = re.search(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", path.name)
    if m:
        y, mo, d, h, mi, s = m.groups()
        return f"{y}-{mo}-{d} {h}:{mi}:{s}"
    return path.name


def find_graphs(csv_path: Path) -> list[Path]:
    """Find graphs in the same directory tree as the CSV."""
    stem = re.search(r"(evaluation_\d+_\d+)", csv_path.name)
    prefix = stem.group(1) if stem else "evaluation_"
    graphs_dir = csv_path.parent / "graphs"
    return sorted(graphs_dir.glob(f"{prefix}*.png"))


def load_scenarios(scenario_file: Path) -> dict:
    """Load scenario_evals.yaml — returns nested dict keyed by (conv_id, turn_id)."""
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
                "expected_keywords": turn.get("expected_keywords") or [],
                "expected_tool_calls": turn.get("expected_tool_calls") or [],
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
    try:
        v = float(score)
    except (ValueError, TypeError):
        return "—"
    filled = round(v * width)
    return f"`{'█' * filled}{'░' * (width - filled)}` {v:.2f}"


def fmt_keywords(keywords: list) -> str:
    """Format expected_keywords as 'ALL(a, b) OR ALL(c, d)' alternatives."""
    if not keywords:
        return ""
    parts = [" + ".join(f"`{k}`" for k in group) for group in keywords]
    return "  \n".join(f"Option {i+1}: {p}" for i, p in enumerate(parts))


def _is_expected_format(tool_calls: list) -> bool:
    """
    Detect expected_tool_calls (3-level) vs actual tool_calls (2-level).
    expected: [alternatives → [sequences → [tools]]]  → tc[0][0] is a list
    actual:   [sequences → [tools]]                   → tc[0][0] is a dict
    """
    try:
        return isinstance(tool_calls[0][0], list)
    except (IndexError, TypeError):
        return False


def fmt_tool_calls(tool_calls: list, label: str = "") -> list[str]:
    """Format expected_tool_calls or actual tool_calls as markdown."""
    if not tool_calls:
        return []
    lines = []
    if label:
        lines += [f"**{label}**", ""]

    if _is_expected_format(tool_calls):
        # expected_tool_calls: [alternatives → [sequences → [tools]]]
        for a_idx, alternative in enumerate(tool_calls):
            if not alternative:
                lines += [f"*Alternative {a_idx + 1}: no tools (skip scenario)*", ""]
                continue
            lines.append(f"*Alternative {a_idx + 1}:*")
            for sequence in alternative:
                tools = sequence if isinstance(sequence, list) else [sequence]
                for tool in tools:
                    if isinstance(tool, dict):
                        name = tool.get("tool_name", "?")
                        args = tool.get("arguments", {})
                        arg_str = ", ".join(f"{k}={v}" for k, v in args.items()) if args else ""
                        lines.append(f"  - `{name}`({arg_str})")
            lines.append("")
    else:
        # actual tool_calls: [sequences → [tools]]
        for sequence in tool_calls:
            tools = sequence if isinstance(sequence, list) else [sequence]
            for tool in tools:
                if isinstance(tool, dict):
                    name = tool.get("tool_name", "?")
                    args = tool.get("arguments", {})
                    arg_str = ", ".join(f"{k}={v}" for k, v in list(args.items())[:4])
                    if len(args) > 4:
                        arg_str += ", …"
                    lines.append(f"- `{name}`({arg_str})")
        lines.append("")
    return lines


# ── Markdown generation ───────────────────────────────────────────────────────

def generate_md(
    csv_path: Path,
    json_path: Path,
    graphs: list[Path],
    scenarios: dict,
    output: Path,
    _scenario_name: str = "",
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
        f"| {result_emoji('PASS')} Pass    | {overall.get('PASS', 0)} | {overall.get('pass_rate', 0):.1f}% |",
        f"| {result_emoji('FAIL')} Fail    | {overall.get('FAIL', 0)} | {overall.get('fail_rate', 0):.1f}% |",
        f"| {result_emoji('ERROR')} Error   | {overall.get('ERROR', 0)} | {overall.get('error_rate', 0):.1f}% |",
        f"| {result_emoji('SKIPPED')} Skipped | {overall.get('SKIPPED', 0)} | {overall.get('skipped_rate', 0):.1f}% |",
        "",
        "### Token Usage",
        "",
        "| | Tokens |",
        "|---|---|",
        f"| Judge LLM input  | {overall.get('total_judge_llm_input_tokens', 0):,} |",
        f"| Judge LLM output | {overall.get('total_judge_llm_output_tokens', 0):,} |",
        f"| API input  | {overall.get('total_api_input_tokens', 0):,} |",
        f"| API output | {overall.get('total_api_output_tokens', 0):,} |",
        f"| **Total** | **{overall.get('total_tokens', 0):,}** |",
        "",
    ]

    if latency:
        lines += [
            "### Agent Latency",
            "",
            "| | Seconds |",
            "|---|---|",
            f"| Mean   | {latency.get('mean', 0):.2f}s |",
            f"| Median | {latency.get('median', 0):.2f}s |",
            f"| Min    | {latency.get('min', 0):.2f}s |",
            f"| Max    | {latency.get('max', 0):.2f}s |",
            f"| p95    | {latency.get('p95', 0):.2f}s |",
            "",
        ]

    # ── By metric ─────────────────────────────────────────────────────────────
    lines += ["## Results by Metric", ""]
    lines += ["| Metric | ✅ Pass | ❌ Fail | ⚠️ Error | Pass Rate | Mean Score |"]
    lines += ["|--------|--------|--------|---------|-----------|------------|"]
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
            label = g.stem.replace(re.search(r"evaluation_\d+_\d+_?", g.stem).group(), "").replace("_", " ").strip().title()
            rel = g.relative_to(output.parent)
            lines += [f"### {label}", "", f"![{label}]({rel})", ""]

    # ── Per-scenario details ───────────────────────────────────────────────────
    lines += ["## Scenario Results", ""]

    # Build a lookup from CSV: (turn_id, metric) → row
    convs: dict = {}
    for row in rows:
        gid = row.get("conversation_group_id", "")
        convs.setdefault(gid, []).append(row)

    for gid, conv_rows in convs.items():
        sc = scenarios.get(gid, {})
        desc = sc.get("_description", "")
        conv_stats = by_conv.get(gid, {})
        total_c = conv_stats.get("pass", 0) + conv_stats.get("fail", 0) + conv_stats.get("error", 0)

        lines += [f"### `{gid}`", ""]
        if desc:
            lines += [f"> {desc}", ""]
        lines += [
            f"**Pass rate:** {conv_stats.get('pass_rate', 0):.1f}% ({conv_stats.get('pass',0)}/{total_c})",
            "",
        ]

        # Group rows by turn_id
        turns: dict = {}
        for row in conv_rows:
            turns.setdefault(row.get("turn_id", ""), []).append(row)

        for tid, turn_rows in turns.items():
            turn_sc = sc.get(tid, {})
            query = turn_sc.get("query", "")
            expected_resp = turn_sc.get("expected_response", "")
            expected_kw = turn_sc.get("expected_keywords", [])
            expected_tc = turn_sc.get("expected_tool_calls", [])

            # Actual tool_calls from CSV (from any row of this turn)
            actual_tc_raw = ""
            for r in turn_rows:
                if r.get("tool_calls"):
                    actual_tc_raw = r["tool_calls"]
                    break
            actual_tc = json.loads(actual_tc_raw) if actual_tc_raw else []

            first = turn_rows[0]
            response = first.get("response", "").strip()

            turn_metrics = turn_sc.get("turn_metrics", [])
            metrics_str = " · ".join(f"`{m}`" for m in turn_metrics) if turn_metrics else ""

            lines += [f"#### Turn: `{tid}`", ""]

            if metrics_str:
                lines += [f"**Metrics evaluated:** {metrics_str}", ""]

            if query:
                lines += [f"**Query:** {query}", ""]

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

            # Expected keywords
            if expected_kw:
                lines += ["<details>", "<summary>Expected keywords</summary>", ""]
                lines.append(fmt_keywords(expected_kw))
                lines += ["", "</details>", ""]

            # Expected tool calls
            if expected_tc:
                lines += ["<details>", "<summary>Expected tool calls</summary>", ""]
                lines += fmt_tool_calls(expected_tc)
                lines += ["</details>", ""]

            # Actual tool calls
            if actual_tc:
                lines += ["<details>", "<summary>Actual tool calls</summary>", ""]
                lines += fmt_tool_calls(actual_tc)
                lines += ["</details>", ""]

            # Expected response
            if expected_resp:
                lines += ["<details>", "<summary>Expected response</summary>", "", expected_resp, "", "</details>", ""]

            # Judge reasons
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

            # Agent response
            if response:
                truncated = response[:800] + ("…" if len(response) > 800 else "")
                lines += [
                    "<details>",
                    "<summary>Agent response</summary>",
                    "",
                    "```",
                    truncated,
                    "```",
                    "",
                    "</details>",
                    "",
                ]

        lines += ["---", ""]

    lines += [f"*Generated from `{csv_path.name}` and `{json_path.name}`.*"]

    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ RESULTS.md written to {output}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    root = Path(__file__).parent.parent

    parser = argparse.ArgumentParser(description="Generate RESULTS.md from evaluation output")
    parser.add_argument("--results-dir", default=str(root / "results"))
    parser.add_argument("--scenarios-dir", default=str(root / "scenarios"),
                        help="Directory containing conversations.yaml or scenario eval_data.yaml files")
    parser.add_argument("--output", default=str(root / "RESULTS.md"))
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    scenarios_dir = Path(args.scenarios_dir)
    output = Path(args.output)

    runs = find_all_runs(results_dir)
    if not runs:
        print(f"ERROR: No evaluation results found under {results_dir}", file=sys.stderr)
        sys.exit(1)

    # Load conversations: prefer scenarios/conversations.yaml, fall back to scenarios/*/eval_data.yaml
    all_scenarios: dict = {}
    if scenarios_dir.exists():
        conversations_file = scenarios_dir / "conversations.yaml"
        if conversations_file.exists():
            all_scenarios.update(load_scenarios(conversations_file))
        else:
            for scenario_dir in sorted(scenarios_dir.iterdir()):
                eval_file = scenario_dir / "eval_data.yaml"
                if eval_file.exists():
                    all_scenarios.update(load_scenarios(eval_file))

    if len(runs) == 1:
        # Single run (flat layout or single scenario) → full report at root
        _, csv_path, json_path = runs[0]
        print(f"Using: {csv_path.name}")
        graphs = find_graphs(csv_path)
        generate_md(csv_path, json_path, graphs, all_scenarios, output)
    else:
        # Multiple runs (per-subdir) → combined full report at root
        lines_all: list[str] = [
            "# Evaluation Results — All Scenarios",
            "",
            f"**Scenarios:** {len(runs)}  ",
            "",
            "---",
            "",
        ]
        for name, csv_path, json_path in runs:
            print(f"Including: {name} / {csv_path.name}")
            graphs = find_graphs(csv_path)
            tmp = output.parent / f".tmp_results_{name}.md"
            generate_md(csv_path, json_path, graphs, all_scenarios, tmp)
            lines_all += [f"## Scenario: `{name}`", ""]
            lines_all += tmp.read_text().splitlines()
            tmp.unlink()
            lines_all += ["", "---", ""]

        output.write_text("\n".join(lines_all), encoding="utf-8")
        print(f"✓ Combined RESULTS.md written to {output}")


if __name__ == "__main__":
    main()
