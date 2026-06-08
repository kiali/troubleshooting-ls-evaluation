#!/usr/bin/env python3
"""
generate_results.py

Reads ALL evaluation CSV+JSON pairs from results/ and generates:
  - RESULTS.md  — summary comparison table: rows=conversations, columns=api models
  - results/<conv>_<model>.md  — full per-run detail pages

Each CSV+JSON pair represents one (conversation, provider/model) run.
Provider and model are extracted from configuration.llm.* and configuration.api.* in the JSON.
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

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
    """One CSV+JSON+graphs bundle for a single (conversation, model) run."""

    def __init__(self, csv_path: Path, json_path: Path):
        self.csv_path = csv_path
        self.json_path = json_path
        self.prefix = extract_prefix(csv_path)
        self.timestamp = extract_timestamp(csv_path)
        self.rows = load_csv(csv_path)
        self.summary = load_json(json_path)
        self.gid = self.rows[0].get("conversation_group_id", "?") if self.rows else "?"

        cfg = self.summary.get("configuration", {})
        self.api_model = cfg.get("api", {}).get("model", "unknown")
        self.api_provider = cfg.get("api", {}).get("provider", "unknown")
        self.llm_provider = cfg.get("llm", {}).get("provider", "unknown")
        self.llm_model = cfg.get("llm", {}).get("model", "unknown")

        # Label for table columns and file names
        self.model_label = self.api_model

    @property
    def graphs(self) -> dict[str, Path]:
        result = {}
        graphs_dir = self.csv_path.parent / "graphs"
        for g in sorted(graphs_dir.glob(f"{self.prefix}*.png")):
            m = re.search(r"evaluation_\d+_\d+_(.*?)\.png$", g.name)
            if m:
                result[m.group(1)] = g
        return result

    @property
    def overall(self) -> dict:
        return self.summary.get("summary_stats", {}).get("overall", {})

    @property
    def pass_rate(self) -> float:
        return self.overall.get("pass_rate", 0.0)


def find_all_runs(results_dir: Path) -> list[ConvRun]:
    """Find ALL CSV+JSON pairs, keeping the latest per (gid, api_model)."""
    csvs = sorted(results_dir.rglob("evaluation_*_detailed.csv"), reverse=True)
    jsons_by_prefix: dict[str, Path] = {}
    for j in results_dir.rglob("evaluation_*_summary.json"):
        jsons_by_prefix[extract_prefix(j)] = j

    seen: set[tuple] = set()
    runs: list[ConvRun] = []

    for csv_path in csvs:
        prefix = extract_prefix(csv_path)
        json_path = jsons_by_prefix.get(prefix)
        if not json_path:
            continue
        run = ConvRun(csv_path, json_path)
        key = (run.gid, run.api_model)
        if key not in seen:
            seen.add(key)
            runs.append(run)

    return sorted(runs, key=lambda r: (r.gid, r.api_model))


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


# ── Per-run detail page ───────────────────────────────────────────────────────

def generate_detail_md(run: ConvRun, sc: dict, output: Path) -> None:
    o = run.overall
    tot = o.get("TOTAL", 0)
    p = o.get("PASS", 0)
    f = o.get("FAIL", 0)
    e = o.get("ERROR", 0)
    rate = f"{p/tot*100:.0f}%" if tot else "—"
    icon = "✅" if f + e == 0 else "❌"
    desc = sc.get("_description", "")

    lines: list[str] = [
        f"# {icon} {run.gid}",
        "",
        f"**OLS model:** `{run.api_provider}/{run.api_model}` &nbsp;|&nbsp; "
        f"**Judge:** `{run.llm_provider}/{run.llm_model}`  ",
        f"**Run:** {run.timestamp} &nbsp;|&nbsp; "
        f"**Evaluations:** {tot} &nbsp;|&nbsp; "
        f"✅ {p} PASS &nbsp; ❌ {f} FAIL &nbsp; ⚠️ {e} ERROR &nbsp; ({rate})",
    ]
    if desc:
        lines += ["", f"> {desc}"]
    lines += ["", "---", ""]

    # Primary graph inline, rest collapsed
    graphs = run.graphs
    primary = next((k for k in ["pass_rates", "status_breakdown"] if k in graphs), None)
    if primary:
        g = graphs[primary]
        label = primary.replace("_", " ").title()
        rel = g.relative_to(output.parent)
        lines += [f"## {label}", "", f"![{label}]({rel})", ""]
    other_graphs = {k: v for k, v in graphs.items() if k != primary}
    if other_graphs:
        lines += ["<details>", "<summary>More graphs</summary>", ""]
        for key, g in sorted(other_graphs.items()):
            label = key.replace("_", " ").title()
            rel = g.relative_to(output.parent)
            lines += [f"### {label}", "", f"![{label}]({rel})", ""]
        lines += ["</details>", ""]

    # Metrics table
    lines += ["## Metrics", ""]
    lines += ["| Metric | ✅ | ❌ | ⚠️ | Pass Rate | Mean Score |", "|---|---|---|---|---|---|"]
    for metric, s in run.summary.get("summary_stats", {}).get("by_metric", {}).items():
        tot_m = s.get("pass", 0) + s.get("fail", 0) + s.get("error", 0)
        rate_m = s.get("pass", 0) / tot_m * 100 if tot_m else 0
        icon_m = "✅" if rate_m == 100 else ("❌" if rate_m == 0 else "🟡")
        mean = s.get("score_statistics", {}).get("mean", "")
        mean_str = f"{float(mean):.2f}" if mean != "" else "—"
        lines.append(
            f"| `{metric}` | {s.get('pass',0)} | {s.get('fail',0)} | "
            f"{s.get('error',0)} | {icon_m} {rate_m:.0f}% | {mean_str} |"
        )
    lines.append("")

    # Turns
    lines += ["## Turns", ""]
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

        failures = [r for r in turn_rows if r.get("result") != "PASS"]
        if failures:
            lines += ["<details>", "<summary>Judge reasons (failures)</summary>", ""]
            for row in failures:
                js = row.get("judge_scores") or []
                reason = (js[0].get("reason", "") if js else row.get("reason", ""))[:350]
                if reason:
                    lines += [f"**`{row.get('metric_identifier','')}`:** {reason}", ""]
            lines += ["</details>", ""]

        if expected_kw or expected_tc:
            lines += ["<details>", "<summary>Expected signals</summary>", ""]
            if expected_kw:
                lines += ["**Keywords:**  ", fmt_keywords(expected_kw), ""]
            if expected_tc:
                lines += ["**Tool calls:**", ""] + fmt_tool_calls(expected_tc)
            lines += ["</details>", ""]

        if actual_tc:
            lines += ["<details>", "<summary>Actual tool calls</summary>", ""]
            lines += fmt_tool_calls(actual_tc)
            lines += ["</details>", ""]

        if response:
            truncated = response[:1000] + ("…" if len(response) > 1000 else "")
            lines += [
                "<details>", "<summary>Agent response</summary>", "",
                "```", truncated, "```", "", "</details>", "",
            ]

        if expected:
            lines += [
                "<details>", "<summary>Expected response</summary>", "",
                expected, "", "</details>", "",
            ]

    lat = run.summary.get("summary_stats", {}).get("agent_latency_stats", {})
    lines += ["---", "",
        f"*Tokens — Judge: {o.get('total_judge_llm_tokens',0):,} | "
        f"API: {o.get('total_api_tokens',0):,} | "
        f"Total: {o.get('total_tokens',0):,}*"]
    if lat:
        lines.append(f"*Latency — mean: {lat.get('mean',0):.1f}s | p95: {lat.get('p95',0):.1f}s*")

    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"  ✓ {output.name}")


# ── Root summary RESULTS.md ───────────────────────────────────────────────────

def generate_summary_md(runs: list[ConvRun], scenarios: dict, output: Path) -> None:
    """Comparison table: rows=conversations, columns=api models."""

    # Collect unique conversations and models
    all_gids = sorted(set(r.gid for r in runs))
    all_models = sorted(set(r.model_label for r in runs))

    # Build lookup: (gid, model) → run
    run_index: dict[tuple, ConvRun] = {}
    for run in runs:
        run_index[(run.gid, run.model_label)] = run

    # Aggregate totals per model across all conversations
    model_totals: dict[str, dict] = {m: {"pass": 0, "fail": 0, "error": 0, "total": 0} for m in all_models}
    for run in runs:
        o = run.overall
        mt = model_totals[run.model_label]
        mt["pass"] += o.get("PASS", 0)
        mt["fail"] += o.get("FAIL", 0)
        mt["error"] += o.get("ERROR", 0)
        mt["total"] += o.get("TOTAL", 0)

    latest_ts = max(r.timestamp for r in runs) if runs else "—"

    lines: list[str] = [
        "# Evaluation Results",
        "",
        f"**Latest run:** {latest_ts} &nbsp;|&nbsp; **Conversations:** {len(all_gids)} &nbsp;|&nbsp; **Models tested:** {len(all_models)}",
        "",
        "---",
        "",
        "## Summary by Model",
        "",
    ]

    # Model summary row
    lines += ["| Model | Judge | ✅ Pass | ❌ Fail | ⚠️ Error | Pass Rate |", "|---|---|---|---|---|---|"]
    for model in all_models:
        # Find a representative run to get judge info
        rep = next((r for r in runs if r.model_label == model), None)
        judge = f"`{rep.llm_provider}/{rep.llm_model}`" if rep else "—"
        mt = model_totals[model]
        tot = mt["total"]
        rate = f"{mt['pass']/tot*100:.0f}%" if tot else "—"
        icon = "✅" if mt["fail"] + mt["error"] == 0 else ("❌" if mt["pass"] == 0 else "🟡")
        lines.append(f"| `{model}` | {judge} | {mt['pass']} | {mt['fail']} | {mt['error']} | {icon} {rate} |")
    lines.append("")

    # Comparison table: rows=conversations, columns=models
    lines += ["## Results by Conversation and Model", ""]
    header = "| Conversation | " + " | ".join(f"`{m}`" for m in all_models) + " |"
    sep = "|---|" + "|".join("---" for _ in all_models) + "|"
    lines += [header, sep]

    for gid in all_gids:
        desc = scenarios.get(gid, {}).get("_description", "")
        cells = []
        for model in all_models:
            run = run_index.get((gid, model))
            if run:
                o = run.overall
                tot = o.get("TOTAL", 0)
                p = o.get("PASS", 0)
                f = o.get("FAIL", 0)
                e = o.get("ERROR", 0)
                rate_pct = f"{p/tot*100:.0f}%" if tot else "—"
                icon = "✅" if f + e == 0 else ("❌" if p == 0 else "🟡")
                # Link to detail page
                safe_model = re.sub(r"[^a-zA-Z0-9._-]", "-", model)
                detail = f"results/{gid}_{safe_model}.md"
                cells.append(f"[{icon} {rate_pct} ({p}/{tot})]({detail})")
            else:
                cells.append("—")
        row_label = f"`{gid}`"
        lines.append("| " + row_label + " | " + " | ".join(cells) + " |")
    lines.append("")

    if len(all_models) > 1:
        lines += ["## Metric Breakdown by Model", ""]
        # Collect all metrics across all runs
        all_metrics: list[str] = []
        for run in runs:
            for m in run.summary.get("summary_stats", {}).get("by_metric", {}).keys():
                if m not in all_metrics:
                    all_metrics.append(m)

        h2 = "| Metric | " + " | ".join(f"`{m}`" for m in all_models) + " |"
        s2 = "|---|" + "|".join("---" for _ in all_models) + "|"
        lines += [h2, s2]
        for metric in sorted(all_metrics):
            cells = []
            for model in all_models:
                model_runs = [r for r in runs if r.model_label == model]
                p = sum(r.summary.get("summary_stats",{}).get("by_metric",{}).get(metric,{}).get("pass",0) for r in model_runs)
                f = sum(r.summary.get("summary_stats",{}).get("by_metric",{}).get(metric,{}).get("fail",0) for r in model_runs)
                e = sum(r.summary.get("summary_stats",{}).get("by_metric",{}).get(metric,{}).get("error",0) for r in model_runs)
                tot = p + f + e
                if tot:
                    rate = p / tot * 100
                    icon = "✅" if rate == 100 else ("❌" if rate == 0 else "🟡")
                    cells.append(f"{icon} {rate:.0f}% ({p}/{tot})")
                else:
                    cells.append("—")
            lines.append("| `" + metric + "` | " + " | ".join(cells) + " |")
        lines.append("")

    lines += ["## Scenario Detail Pages", ""]
    for gid in all_gids:
        desc = scenarios.get(gid, {}).get("_description", "")
        desc_str = f" — {desc}" if desc else ""
        lines.append(f"### `{gid}`{desc_str}")
        lines.append("")
        for model in all_models:
            run = run_index.get((gid, model))
            if run:
                safe_model = re.sub(r"[^a-zA-Z0-9._-]", "-", model)
                detail = f"results/{gid}_{safe_model}.md"
                o = run.overall
                p, tot = o.get("PASS", 0), o.get("TOTAL", 0)
                rate = f"{p/tot*100:.0f}%" if tot else "—"
                icon = "✅" if o.get("FAIL",0) + o.get("ERROR",0) == 0 else "❌"
                lines.append(f"- [{icon} `{model}` — {rate} ({p}/{tot})]({detail}) — {run.timestamp}")
        lines.append("")

    lines += ["*Generated by `scripts/generate_results.py`*"]
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ RESULTS.md written to {output}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    root = Path(__file__).parent.parent
    parser = argparse.ArgumentParser(description="Generate RESULTS.md with multi-model comparison")
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

    # Summary of what was found
    model_conv = defaultdict(list)
    for r in runs:
        model_conv[r.model_label].append(r.gid)
    for model, convs in sorted(model_conv.items()):
        print(f"  {model}: {', '.join(sorted(convs))}")

    # Load scenario metadata
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

    # Generate per-run detail pages
    print("Generating detail pages:")
    for run in runs:
        sc = all_scenarios.get(run.gid, {})
        safe_model = re.sub(r"[^a-zA-Z0-9._-]", "-", run.model_label)
        detail_output = results_dir / f"{run.gid}_{safe_model}.md"
        generate_detail_md(run, sc, detail_output)

    # Generate root summary
    generate_summary_md(runs, all_scenarios, output)


if __name__ == "__main__":
    main()
