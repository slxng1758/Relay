"""
Evals runner for the Relay multi-agent system.

Usage:
  python evals/run_evals.py --routing             # routing accuracy only
  python evals/run_evals.py --retrieval           # retrieval quality only
  python evals/run_evals.py --answers             # answer quality only
  python evals/run_evals.py --all                 # run all three suites
  python evals/run_evals.py --all --verbose       # per-case detail
  python evals/run_evals.py --all --no-save       # skip writing results JSON

Results are written to evals/results/{timestamp}.json and also printed as a
summary table. The process exits with code 1 if any metric falls below the
configured thresholds — suitable for wiring to CI.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import typer

# ── Pass/fail thresholds ─────────────────────────────────────────────────────

# Routing: macro F1 across all cases (tool selection precision+recall combined)
ROUTING_F1_THRESHOLD = 0.70

# Routing: fraction of cases where expected == actual tool set exactly
ROUTING_EXACT_MATCH_THRESHOLD = 0.50

# Retrieval: mean recall@3 (most important — finds the right doc in top 3)
RETRIEVAL_RECALL_AT_3_THRESHOLD = 0.60

# Retrieval: mean MRR (first relevant result rank)
RETRIEVAL_MRR_THRESHOLD = 0.50

# Answer quality: mean overall judge score across all four dimensions (out of 5)
ANSWER_MEAN_SCORE_THRESHOLD = 3.0

# Answer quality: mean groundedness specifically (hallucination guard)
ANSWER_GROUNDEDNESS_THRESHOLD = 3.0

RESULTS_DIR = Path(__file__).parent / "results"

app = typer.Typer(add_completion=False)


def _json_default(obj: object) -> object:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    raise TypeError(f"Not JSON serialisable: {type(obj)}")


def _save_results(payload: dict) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"eval_{ts}.json"
    path.write_text(json.dumps(payload, indent=2, default=_json_default))
    return path


def _git_sha() -> str:
    try:
        import subprocess
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def _print_routing_table(report: "RoutingReport") -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="Routing Accuracy", show_lines=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_column("Threshold", justify="right")
    table.add_column("Pass?", justify="center")

    def _row(label: str, val: float, threshold: float) -> None:
        passed = val >= threshold
        color = "green" if passed else "red"
        table.add_row(
            label,
            f"{val:.3f}",
            f"{threshold:.3f}",
            f"[{color}]{'✓' if passed else '✗'}[/{color}]",
        )

    _row("Macro F1", report.macro_f1, ROUTING_F1_THRESHOLD)
    _row("Macro Precision", report.macro_precision, 0.0)
    _row("Macro Recall", report.macro_recall, 0.0)
    _row("Exact Match Rate", report.exact_match_rate, ROUTING_EXACT_MATCH_THRESHOLD)
    table.add_row("Cases", str(report.n_cases), "", "")
    table.add_row("Skipped", str(report.n_skipped), "", "")
    console.print(table)


def _print_retrieval_table(report: "RetrievalReport") -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="Retrieval Quality", show_lines=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_column("Threshold", justify="right")
    table.add_column("Pass?", justify="center")

    def _row(label: str, val: float, threshold: float) -> None:
        passed = val >= threshold
        color = "green" if passed else "red"
        table.add_row(
            label,
            f"{val:.3f}",
            f"{threshold:.3f}" if threshold else "—",
            f"[{color}]{'✓' if passed else '✗'}[/{color}]" if threshold else "—",
        )

    for k in (1, 3, 5, 10):
        threshold = RETRIEVAL_RECALL_AT_3_THRESHOLD if k == 3 else 0.0
        _row(f"Recall@{k}", report.mean_recall_at_k.get(k, 0.0), threshold)

    _row("MRR", report.mean_mrr, RETRIEVAL_MRR_THRESHOLD)
    _row("NDCG@5", report.mean_ndcg_at_5, 0.0)
    table.add_row("Cases", str(report.n_cases), "", "")
    table.add_row("Skipped", str(report.n_skipped), "", "")
    console.print(table)


def _print_answer_table(report: "AnswerReport") -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="Answer Quality (LLM-as-Judge, 1–5 scale)", show_lines=True)
    table.add_column("Dimension", style="bold")
    table.add_column("Mean Score", justify="right")
    table.add_column("Threshold", justify="right")
    table.add_column("Pass?", justify="center")

    def _row(label: str, val: float, threshold: float) -> None:
        passed = val >= threshold
        color = "green" if passed else "red"
        table.add_row(
            label,
            f"{val:.2f}",
            f"{threshold:.1f}",
            f"[{color}]{'✓' if passed else '✗'}[/{color}]",
        )

    _row("Relevance", report.mean_relevance, 0.0)
    _row("Groundedness", report.mean_groundedness, ANSWER_GROUNDEDNESS_THRESHOLD)
    _row("Completeness", report.mean_completeness, 0.0)
    _row("Actionability", report.mean_actionability, 0.0)
    _row("Overall (mean)", report.mean_overall, ANSWER_MEAN_SCORE_THRESHOLD)
    table.add_row("Cases", str(report.n_cases), "", "")
    table.add_row("Skipped", str(report.n_skipped), "", "")
    console.print(table)


def _routing_passes(report: "RoutingReport") -> bool:
    return (
        report.macro_f1 >= ROUTING_F1_THRESHOLD
        and report.exact_match_rate >= ROUTING_EXACT_MATCH_THRESHOLD
    )


def _retrieval_passes(report: "RetrievalReport") -> bool:
    return (
        report.mean_recall_at_k.get(3, 0.0) >= RETRIEVAL_RECALL_AT_3_THRESHOLD
        and report.mean_mrr >= RETRIEVAL_MRR_THRESHOLD
    )


def _answers_pass(report: "AnswerReport") -> bool:
    return (
        report.mean_overall >= ANSWER_MEAN_SCORE_THRESHOLD
        and report.mean_groundedness >= ANSWER_GROUNDEDNESS_THRESHOLD
    )


async def _run(
    routing: bool,
    retrieval: bool,
    answers: bool,
    verbose: bool,
    no_save: bool,
) -> int:
    """Returns exit code (0 = all pass, 1 = at least one suite failed)."""
    from rich.console import Console
    console = Console()

    payload: dict = {
        "git_sha": _git_sha(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "suites": {},
    }
    all_pass = True

    if routing:
        console.rule("[bold blue]Routing Eval")
        from evals.evaluators.routing import run as run_routing, RoutingReport
        report: RoutingReport = await run_routing(verbose=verbose)
        _print_routing_table(report)
        passed = _routing_passes(report)
        all_pass = all_pass and passed
        payload["suites"]["routing"] = dataclasses.asdict(report)
        payload["suites"]["routing"]["passed"] = passed
        if not passed:
            console.print("[red]Routing: FAIL[/red]")

    if retrieval:
        console.rule("[bold blue]Retrieval Eval")
        from evals.evaluators.retrieval import run as run_retrieval, RetrievalReport
        ret_report: RetrievalReport = await run_retrieval(verbose=verbose)
        _print_retrieval_table(ret_report)
        passed = _retrieval_passes(ret_report)
        all_pass = all_pass and passed
        payload["suites"]["retrieval"] = dataclasses.asdict(ret_report)
        payload["suites"]["retrieval"]["passed"] = passed
        if not passed:
            console.print("[red]Retrieval: FAIL[/red]")

    if answers:
        console.rule("[bold blue]Answer Quality Eval")
        from evals.evaluators.answers import run as run_answers, AnswerReport
        ans_report: AnswerReport = await run_answers(verbose=verbose)
        _print_answer_table(ans_report)
        passed = _answers_pass(ans_report)
        all_pass = all_pass and passed
        payload["suites"]["answers"] = dataclasses.asdict(ans_report)
        payload["suites"]["answers"]["passed"] = passed
        if not passed:
            console.print("[red]Answer quality: FAIL[/red]")

    payload["all_passed"] = all_pass

    if not no_save:
        out_path = _save_results(payload)
        console.print(f"\n[dim]Results saved → {out_path}[/dim]")

    return 0 if all_pass else 1


@app.command()
def main(
    routing: bool = typer.Option(False, "--routing", help="Run routing accuracy eval"),
    retrieval: bool = typer.Option(False, "--retrieval", help="Run retrieval quality eval"),
    answers: bool = typer.Option(False, "--answers", help="Run answer quality eval"),
    all_suites: bool = typer.Option(False, "--all", help="Run all three eval suites"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Print per-case detail"),
    no_save: bool = typer.Option(False, "--no-save", help="Skip writing results JSON"),
) -> None:
    if all_suites:
        routing = retrieval = answers = True

    if not (routing or retrieval or answers):
        typer.echo("Specify at least one suite: --routing, --retrieval, --answers, or --all")
        raise typer.Exit(1)

    exit_code = asyncio.run(_run(
        routing=routing,
        retrieval=retrieval,
        answers=answers,
        verbose=verbose,
        no_save=no_save,
    ))
    raise typer.Exit(exit_code)


if __name__ == "__main__":
    app()
