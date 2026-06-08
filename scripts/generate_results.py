#!/usr/bin/env python3
"""
generate_results.py

Each evaluation run produces one CSV + JSON pair (same timestamp).
The conversation_group_id column in the CSV identifies the conversation.
Multiple runs → multiple pairs → this script merges them all.

Structure of RESULTS.md:
  - Header with aggregate stats
  - Summary table (one row per conversation)
  - Metrics breakdown (aggregated)
  - Per-conversation collapsible sections (each with its own graphs)
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML required. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


# ── Data loading ──────────────────────────────────────────────────────────────

def extract_timestamp(path: Path) -> str:
    m = re.search(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", path.name)
    if m:
        y, mo, d, h, mi, s = m.groups()
        return f"{y}-{mo}-{d} {h}:{mi}:{s}"
    return path.name


def extract_prefix(path: Path) -> str:
    m = re.search(r"(evaluation_\d+_\d+)", path.name)
    return m.group(1) if m else ""


def load_csv(csv_path: Path) -> list[dict]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_json(json_path: Path) -> dict:
    with json_path.open(encoding="utf-8") as f:
        return json.load(f)


def load_scenarios(scenario_file: Path) -> dict:
    scenarios: dict = {}
    if not scenario_file.exists():
        return scenarios
    docs = yaml.safe_load(scenario_file.read_text())
    if not docs:
        return scenarios
    for conv in docs:
        gid = conv.get("conversation_group_id", "")
        scenarios[gid] = {"_description": conv.get("description", ""), "_tag": conv.get("tag", "")}
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


# ── Run discovery ─────────────────────────────────────────────────────────────

class ConvRun:
    """One CSV+JSON+graphs bundle representing a single evaluated conversation."""
    def __init__(self, csv_path: Path, json_path: Path):
        self.csv_path = csv_path
        self.json_path = json_path
        self.prefix = extract_prefix(csv_path)
        self.timestamp = extract_timestamp(csv_path)
        self.rows = load_csv(csv_path)
        self.summary = load_json(json_path)
        self.gid = self.rows[0].get("conversation_group_id", "?") if self.rows else "?"

    @property
    def graphs(self) -> dict[str, Path]:
        result = {}
        graphs_dir = self.csv_path.parent / "graphs"
        for g in sorted(graphs_dir.glob(f"{self.prefix}*.png")):
            m = re.search(r"evaluation_\d+_\d+_(.*?)\.png$", g.name)
            if m:
                result[m.group(1)] = g
        return result


def find_all_runs(results_dir: Path) -> list[ConvRun]:
    """
    Find all CSV+JSON pairs in results_dir (flat layout, one pair per conversation).
    For each conversation_group_id, keep only the LATEST run.
    """
    csvs = sorted(results_dir.rglob("evaluation_*_detailed.csv"), reverse=True)
    jsons_by_prefix = {}
    for j in results_dir.rglob("evaluation_*_summary.json"):
        jsons_by_prefix[extract_prefix(j)] = j

    seen_gids: set[str] = set()
    runs: list[ConvRun] = []

    for csv_path in csvs:
        prefix = extract_prefix(csv_path)
        json_path = jsons_by_prefix.get(prefix)
        if not json_path:
            continue
        run = ConvRun(csv_path, json_path)
        if run.gid not in seen_gids:
            seen_gids.add(run.gid)
            runs.append(run)

    return sorted(runs, key=lambda r: r.gid)


# ── Formatting helpers ────────────────────────────────────────────────────────

def result_emoji(result: str) -> str:
    return {"PASS": "✅", "FAIL": "❌", "ERROR": "⚠️", "SKIPPED": "⏭️"}.get(result, result)


def score_bar(score: str, width: int = 16) -> str:
    try:
        v = float(score)
    except (ValueError, TypeError):
        return "—"
    filled = round(v * width)
    return f"`{'█' * filled}{'░' * (width - filled)}` {v:.2f}"


def fmt_keywords(keywords: list) -> str:
    if not keywords:
        return ""
    parts = [" + ".join(f"`{k}`" for k in g) for g in keywords]
    return "  \n".join(f"Option {i+1}: {p}" for i, p in enumerate(parts))


def _is_expected_format(tc: list) -> bool:
    try:
        return isinstance(tc[0][0], list)
    except (IndexError, TypeError):
        return False


def fmt_tool_calls(tool_calls: list) -> list[str]:
    if not tool_calls:
        return []
    lines: list[str] = []
    if _is_expected_format(tool_calls):
        for a_idx, alt in enumerate(tool_calls):
            if not alt:
                lines += [f"*Alt {a_idx+1}: no tools*", ""]
                continue
            lines.append(f"*Alt {a_idx+1}:*")
            for seq in alt:
                tools = seq if isinstance(seq, list) else [seq]
                for t in tools:
                    if isinstance(t, dict):
                        args = t.get("arguments", {})
                        arg_str = ", ".join(f"{k}={v}" for k, v in args.items()) if args else ""
                        lines.append(f"  - `{t.get('tool_name','?')}`({arg_str})")
            lines.append("")
    else:
        for seq in tool_calls:
            tools = seq if isinstance(seq, list) else [seq]
            for t in tools:
                if isinstance(t, dict):
                    args = t.get("arguments", {})
                    arg_str = ", ".join(f"{k}={v}" for k, v in list(args.items())[:4])
                    if len(args) > 4:
                        arg_str += ", …"
                    lines.append(f"- `{t.get('tool_name','?')}`({arg_str})")
        lines.append("")
    return lines


# ── Markdown generation ───────────────────────────────────────────────────────

def generate_md(runs: list[ConvRun], scenarios: dict, output: Path) -> None:
    if not runs:
        print("ERROR: No runs found", file=sys.stderr)
        sys.exit(1)

    # ── Aggregate stats across all runs ──────────────────────────────────────
    total_pass = total_fail = total_error = total_evals = 0
    metric_agg: dict[str, dict] = defaultdict(lambda: {"pass": 0, "fail": 0, "error": 0, "scores": []})
    conv_stats: dict[str, dict] = {}

    for run in runs:
        o = run.summary.get("summary_stats", {}).get("overall", {})
        total_pass += o.get("PASS", 0)
        total_fail += o.get("FAIL", 0)
        total_error += o.get("ERROR", 0)
        total_evals += o.get("TOTAL", 0)
        conv_stats[run.gid] = {
            "pass": o.get("PASS", 0), "fail": o.get("FAIL", 0),
            "error": o.get("ERROR", 0), "total": o.get("TOTAL", 0),
            "timestamp": run.timestamp,
        }
        for m, s in run.summary.get("summary_stats", {}).get("by_metric", {}).items():
            metric_agg[m]["pass"] += s.get("pass", 0)
            metric_agg[m]["fail"] += s.get("fail", 0)
            metric_agg[m]["error"] += s.get("error", 0)
            mean = s.get("score_statistics", {}).get("mean")
            if mean is not None:
                metric_agg[m]["scores"].append(float(mean))

    latest_ts = runs[-1].timestamp if runs else "—"
    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────────
    lines += [
        "# Evaluation Results",
        "",
        f"**Latest run:** {latest_ts} &nbsp;|&nbsp; "
        f"**Conversations:** {len(runs)} &nbsp;|&nbsp; "
        f"**Evaluations:** {total_evals} &nbsp;|&nbsp; "
        f"✅ {total_pass} &nbsp; ❌ {total_fail} &nbsp; ⚠️ {total_error}",
        "",
        "---",
        "",
    ]

    # ── Summary table ─────────────────────────────────────────────────────────
    lines += ["## Summary", ""]
    lines += ["| Conversation | Run | ✅ | ❌ | ⚠️ | Pass Rate |", "|---|---|---|---|---|---|"]
    for run in runs:
        s = conv_stats[run.gid]
        tot = s["total"]
        rate = f"{s['pass']/tot*100:.0f}%" if tot else "—"
        icon = "✅" if s["fail"] + s["error"] == 0 else ("❌" if s["pass"] == 0 else "🟡")
        lines.append(
            f"| `{run.gid}` | {s['timestamp']} | {s['pass']} | {s['fail']} | {s['error']} | {icon} {rate} |"
        )
    lines.append("")

    # ── Metrics breakdown (aggregated) ────────────────────────────────────────
    lines += ["## Metrics Breakdown", ""]
    lines += ["| Metric | ✅ | ❌ | ⚠️ | Pass Rate | Mean Score |", "|---|---|---|---|---|---|"]
    for metric, s in sorted(metric_agg.items()):
        tot = s["pass"] + s["fail"] + s["error"]
        rate = s["pass"] / tot * 100 if tot else 0
        icon = "✅" if rate == 100 else ("❌" if rate == 0 else "🟡")
        mean_str = f"{sum(s['scores'])/len(s['scores']):.2f}" if s["scores"] else "—"
        lines.append(
            f"| `{metric}` | {s['pass']} | {s['fail']} | {s['error']} | {icon} {rate:.0f}% | {mean_str} |"
        )
    lines.append("")

    # ── Per-conversation sections ─────────────────────────────────────────────
    lines += ["## Scenario Details", ""]

    for run in runs:
        sc = scenarios.get(run.gid, {})
        desc = sc.get("_description", "")
        s = conv_stats[run.gid]
        tot = s["total"]
        rate = f"{s['pass']/tot*100:.0f}%" if tot else "—"
        icon = "✅" if s["fail"] + s["error"] == 0 else "❌"

        desc_suffix = f" — {desc}" if desc else ""
        lines += [
            "<details>",
            f"<summary>{icon} {run.gid} — {rate} ({s['pass']}/{tot}) — {run.timestamp}{desc_suffix}</summary>",
            "",
        ]

        # Graphs (collapsed inside each conversation)
        graphs = run.graphs
        primary_key = next((k for k in ["pass_rates", "status_breakdown"] if k in graphs), None)
        if graphs:
            lines += ["<details>", "<summary>📊 Graphs</summary>", ""]
            for key, g in sorted(graphs.items()):
                label = key.replace("_", " ").title()
                rel = g.relative_to(output.parent)
                lines += [f"**{label}**", "", f"![{label}]({rel})", ""]
            lines += ["</details>", ""]

        # Token usage (collapsed)
        o = run.summary.get("summary_stats", {}).get("overall", {})
        lat = run.summary.get("summary_stats", {}).get("agent_latency_stats", {})
        lines += [
            "<details>",
            "<summary>⚙️ Tokens &amp; latency</summary>",
            "",
            f"Judge: {o.get('total_judge_llm_tokens',0):,} tokens &nbsp;|&nbsp; "
            f"API: {o.get('total_api_tokens',0):,} tokens &nbsp;|&nbsp; "
            f"Total: {o.get('total_tokens',0):,} tokens",
        ]
        if lat:
            lines.append(
                f"Latency — mean: {lat.get('mean',0):.1f}s &nbsp; "
                f"median: {lat.get('median',0):.1f}s &nbsp; "
                f"p95: {lat.get('p95',0):.1f}s"
            )
        lines += ["", "</details>", ""]

        # Turns
        turns: dict = defaultdict(list)
        for row in run.rows:
            turns[row.get("turn_id", "")].append(row)

        for tid, turn_rows in turns.items():
            turn_sc = sc.get(tid, {})
            query = turn_sc.get("query", "")
            expected = turn_sc.get("expected_response", "")
            expected_kw = turn_sc.get("expected_keywords", [])
            expected_tc = turn_sc.get("expected_tool_calls", [])
            turn_metrics = turn_sc.get("turn_metrics", [])

            actual_tc_raw = next((r.get("tool_calls", "") for r in turn_rows if r.get("tool_calls")), "")
            actual_tc = json.loads(actual_tc_raw) if actual_tc_raw else []
            response = turn_rows[0].get("response", "").strip()
            metrics_str = " · ".join(f"`{m}`" for m in turn_metrics) if turn_metrics else ""

            lines += [f"### Turn: `{tid}`", ""]
            if metrics_str:
                lines += [f"**Metrics:** {metrics_str}", ""]
            if query:
                lines += [f"**Query:** {query}", ""]

            lines += ["| Metric | Result | Score |", "|---|---|---|"]
            for row in turn_rows:
                lines.append(
                    f"| `{row.get('metric_identifier','')}` | "
                    f"{result_emoji(row.get('result',''))} {row.get('result','')} | "
                    f"{score_bar(row.get('score',''))} |"
                )
            lines.append("")

            # Judge reasons (failures only)
            failures = [r for r in turn_rows if r.get("result") != "PASS"]
            if failures:
                lines += ["<details>", "<summary>Judge reasons (failures)</summary>", ""]
                for row in failures:
                    js = row.get("judge_scores") or []
                    reason = (js[0].get("reason", "") if js else row.get("reason", ""))[:300]
                    if reason:
                        lines += [f"**`{row.get('metric_identifier','')}`:** {reason}", ""]
                lines += ["</details>", ""]

            # Expected signals
            if expected_kw or expected_tc:
                lines += ["<details>", "<summary>Expected signals</summary>", ""]
                if expected_kw:
                    lines += ["**Keywords:**  ", fmt_keywords(expected_kw), ""]
                if expected_tc:
                    lines += ["**Tool calls:**", ""] + fmt_tool_calls(expected_tc)
                lines += ["</details>", ""]

            # Actual tool calls
            if actual_tc:
                lines += ["<details>", "<summary>Actual tool calls</summary>", ""]
                lines += fmt_tool_calls(actual_tc)
                lines += ["</details>", ""]

            # Agent response
            if response:
                truncated = response[:1000] + ("…" if len(response) > 1000 else "")
                lines += [
                    "<details>", "<summary>Agent response</summary>", "",
                    "```", truncated, "```", "", "</details>", "",
                ]

            # Expected response
            if expected:
                lines += [
                    "<details>", "<summary>Expected response</summary>", "",
                    expected, "", "</details>", "",
                ]

        lines += ["</details>", ""]

    lines += ["*Generated by `scripts/generate_results.py`*"]
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ RESULTS.md written to {output}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    root = Path(__file__).parent.parent
    parser = argparse.ArgumentParser(description="Generate RESULTS.md")
    parser.add_argument("--results-dir", default=str(root / "results"))
    parser.add_argument("--scenarios-dir", default=str(root / "scenarios"))
    parser.add_argument("--output", default=str(root / "RESULTS.md"))
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    scenarios_dir = Path(args.scenarios_dir)
    output = Path(args.output)

    runs = find_all_runs(results_dir)
    if not runs:
        print(f"ERROR: No CSV/JSON pairs found in {results_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(runs)} conversation run(s): {', '.join(r.gid for r in runs)}")

    all_scenarios: dict = {}
    if scenarios_dir.exists():
        conv_file = scenarios_dir / "conversations.yaml"
        if conv_file.exists():
            all_scenarios.update(load_scenarios(conv_file))
        else:
            for sd in sorted(scenarios_dir.iterdir()):
                ef = sd / "eval_data.yaml"
                if ef.exists():
                    all_scenarios.update(load_scenarios(ef))

    generate_md(runs, all_scenarios, output)


if __name__ == "__main__":
    main()
