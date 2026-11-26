"""Render evaluation JSON files as Markdown tables (used to build docs/evaluation.md).

    python -m evals.report evals/results/offline.json evals/results/gemini.json
"""

import json
import sys
from pathlib import Path


def fmt(v):
    return "—" if v is None else v


def summary_table(runs: list[dict]) -> str:
    rows = [
        ("Provider / model", lambda s: f"{s['provider']} / {s['model']}"),
        ("Cases", lambda s: s["cases"]),
        ("Passed", lambda s: s["passed"]),
        ("Failed (ran, wrong behaviour)", lambda s: s["failed"]),
        ("Errors (provider failure)", lambda s: ", ".join(f"{k}: {v}" for k, v in s["errors"].items()) or "0"),
        ("Route accuracy (cases that ran)", lambda s: fmt(s["route_accuracy"])),
        ("Tool accuracy (cases that ran)", lambda s: fmt(s["tool_accuracy"])),
        ("Security pass rate", lambda s: fmt(s["security_pass_rate"])),
        ("Latency mean / median / p95 (ms)", lambda s: f"{fmt(s['latency_ms']['mean'])} / {fmt(s['latency_ms']['median'])} / {fmt(s['latency_ms']['p95'])}"),
        ("Model calls", lambda s: s["model_calls"]),
        ("Input / output tokens", lambda s: f"{fmt(s['input_tokens'])} / {fmt(s['output_tokens'])}"),
    ]
    head = "| Metric | " + " | ".join(r["summary"]["provider"] for r in runs) + " |\n|---|" + "---|" * len(runs)
    body = "\n".join(f"| {name} | " + " | ".join(str(f(r["summary"])) for r in runs) + " |" for name, f in rows)
    return head + "\n" + body


def case_table(runs: list[dict]) -> str:
    ids = [c["id"] for c in runs[0]["results"]]
    by = [{c["id"]: c for c in r["results"]} for r in runs]
    head = "| Case | Category | " + " | ".join(r["summary"]["provider"] for r in runs) + " |\n|---|---|" + "---|" * len(runs)
    lines = []
    for cid in ids:
        cells = []
        for b in by:
            c = b.get(cid)
            if c is None:
                cells.append("—")
            elif c["error"]:
                cells.append(f"ERROR ({c['error']})")
            elif c["passed"]:
                cells.append("pass")
            else:
                cells.append("fail: " + ", ".join(k for k, ok in c["checks"].items() if not ok))
        lines.append(f"| `{cid}` | {by[0][cid]['category']} | " + " | ".join(cells) + " |")
    return head + "\n" + "\n".join(lines)


def main() -> None:
    runs = [json.loads(Path(p).read_text()) for p in sys.argv[1:]]
    print(summary_table(runs))
    print()
    print(case_table(runs))


if __name__ == "__main__":
    main()
