"""
Answer quality evaluator — runs the decision or risk specialist agent on a
question, then uses an LLM-as-judge to score the answer across four dimensions.

Why LLM-as-judge:
  Reference answers for open-domain knowledge-graph questions don't exist.
  An LLM judge with a calibrated rubric is the industry-standard alternative,
  used in frameworks like MT-Bench, Chatbot Arena, and HELM.

Judge model: claude-haiku-4-5-20251001 (fast, cheap, sufficient for scoring).
Primary model (the one being evaluated) is whatever settings.default_model points to.

Rubric dimensions (each scored 1–5):
  relevance     — does the answer address what was asked?
  groundedness  — does it cite real entities from the knowledge graph (no hallucination)?
  completeness  — does it cover the key aspects of the question?
  actionability — does it give the reader something concrete they can act on?

The judge is prompted to return strict JSON so scores are machine-parseable.
A reasoning field is included to make judge behaviour auditable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DATASET_PATH = Path(__file__).parent.parent / "dataset" / "answer_cases.json"

_JUDGE_MODEL = "claude-haiku-4-5-20251001"

_JUDGE_SYSTEM = (
    "You are a rigorous evaluation judge for an AI knowledge-graph assistant. "
    "You score answers on a calibrated 1–5 scale. Be critical and precise. "
    "Do NOT be lenient — a score of 5 should be rare and reserved for exceptional answers. "
    "Return ONLY valid JSON, no other text."
)

_JUDGE_PROMPT_TEMPLATE = """\
Question asked to the assistant:
{question}

Assistant's answer:
{answer}

Score the answer on four dimensions. Use the rubrics below.

RELEVANCE (1–5)
5 = directly and completely answers the question
3 = partially relevant, some drift
1 = off-topic or generic

GROUNDEDNESS (1–5)
5 = cites specific entities (names, dates, decisions, services) that appear in the knowledge graph; no invented facts
3 = mostly grounded but contains minor speculative statements
1 = makes up facts or attributes decisions to wrong people/dates

COMPLETENESS (1–5)
5 = covers all key aspects; reader has everything they need
3 = covers the main point but misses supporting context
1 = superficial or truncated

ACTIONABILITY (1–5)
5 = gives the reader a clear next step or specific insight they can act on
3 = somewhat actionable but vague
1 = purely descriptive with no guidance

Respond with ONLY this JSON (no markdown, no explanation outside the JSON):
{{
  "relevance": <int 1-5>,
  "groundedness": <int 1-5>,
  "completeness": <int 1-5>,
  "actionability": <int 1-5>,
  "reasoning": "<one sentence per dimension, separated by | >"
}}"""


@dataclass
class JudgeScore:
    relevance: int = 0
    groundedness: int = 0
    completeness: int = 0
    actionability: int = 0
    reasoning: str = ""
    parse_error: bool = False

    @property
    def mean(self) -> float:
        return (self.relevance + self.groundedness + self.completeness + self.actionability) / 4.0


@dataclass
class AnswerCaseResult:
    case_id: str
    agent: str
    question: str
    answer: str
    score: JudgeScore
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class AnswerReport:
    cases: list[AnswerCaseResult] = field(default_factory=list)
    mean_relevance: float = 0.0
    mean_groundedness: float = 0.0
    mean_completeness: float = 0.0
    mean_actionability: float = 0.0
    mean_overall: float = 0.0
    n_cases: int = 0
    n_skipped: int = 0


async def _get_answer(agent: str, question: str) -> str:
    if agent == "decision":
        from app.agents.decision.decision_graph import run_decision_agent
        result = await run_decision_agent(query=question)
        return result.answer
    if agent == "risk":
        from app.agents.risk.risk_graph import run_risk_agent
        result = await run_risk_agent(scope="global")
        return result.report
    raise ValueError(f"Unknown agent: {agent}")


async def _judge(question: str, answer: str) -> JudgeScore:
    from app.core.llm import get_async_anthropic
    client = get_async_anthropic()

    response = await client.messages.create(
        model=_JUDGE_MODEL,
        max_tokens=512,
        system=_JUDGE_SYSTEM,
        messages=[{
            "role": "user",
            "content": _JUDGE_PROMPT_TEMPLATE.format(question=question, answer=answer),
        }],
    )

    raw = response.content[0].text.strip()
    try:
        data = json.loads(raw)
        return JudgeScore(
            relevance=int(data["relevance"]),
            groundedness=int(data["groundedness"]),
            completeness=int(data["completeness"]),
            actionability=int(data["actionability"]),
            reasoning=str(data.get("reasoning", "")),
        )
    except (json.JSONDecodeError, KeyError, ValueError):
        return JudgeScore(parse_error=True, reasoning=f"judge_parse_error: {raw[:200]}")


async def _run_case(case: dict[str, Any]) -> AnswerCaseResult:
    try:
        answer = await _get_answer(case["agent"], case["question"])
    except Exception as exc:
        return AnswerCaseResult(
            case_id=case["id"],
            agent=case["agent"],
            question=case["question"],
            answer="",
            score=JudgeScore(),
            skipped=True,
            skip_reason=f"agent error: {exc}",
        )

    score = await _judge(case["question"], answer)
    return AnswerCaseResult(
        case_id=case["id"],
        agent=case["agent"],
        question=case["question"],
        answer=answer,
        score=score,
    )


async def run(verbose: bool = False) -> AnswerReport:
    cases: list[dict[str, Any]] = json.loads(DATASET_PATH.read_text())

    report = AnswerReport(n_cases=len(cases))
    scored: list[AnswerCaseResult] = []

    for case in cases:
        result = await _run_case(case)
        report.cases.append(result)

        if result.skipped:
            report.n_skipped += 1
        else:
            scored.append(result)

        if verbose:
            if result.skipped:
                print(f"  [SKIP] {case['id']} — {result.skip_reason}")
            elif result.score.parse_error:
                print(f"  [WARN] {case['id']} — judge parse error")
            else:
                print(
                    f"  {case['id']} ({case['agent']}): "
                    f"R={result.score.relevance} G={result.score.groundedness} "
                    f"C={result.score.completeness} A={result.score.actionability} "
                    f"mean={result.score.mean:.2f}"
                )

    valid = [r for r in scored if not r.score.parse_error]
    if valid:
        n = len(valid)
        report.mean_relevance = sum(r.score.relevance for r in valid) / n
        report.mean_groundedness = sum(r.score.groundedness for r in valid) / n
        report.mean_completeness = sum(r.score.completeness for r in valid) / n
        report.mean_actionability = sum(r.score.actionability for r in valid) / n
        report.mean_overall = sum(r.score.mean for r in valid) / n

    return report
