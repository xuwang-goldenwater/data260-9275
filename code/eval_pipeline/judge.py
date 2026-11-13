"""
DATA 260 - HW10 Part 2/3: the automated judge (GEval / DeepEval, local model).

Judge model: qwen3:4b through Ollama on this Mac (not the qwen2.5:3b that writes
the answers, so the generator does not grade itself). qwen3:8b was tried first:
on this 8 GB Mac it ran 24% on CPU and one 5-token reply took 81.5 s, a JSON
reply did not finish in 300 s, so it cannot serve 50+ evaluations. qwen3:4b runs
100% on GPU, ~12 s per JSON score.
Settings, fixed for every run in Part 2 and Part 3:
    temperature 0, seed 9275, num_ctx 4096, num_predict 300, think=False,
    JSON-schema output, one call per score (evaluation_steps are written out,
    so GEval does not generate its own).
Note: qwen3:4b ignores think=False in free text (it reasons in the reply), but
with the JSON schema it returns only {"reason", "score"} - every call here uses it.

Score scale 1-5. The rubric bands are (1,1) ... (5,5), so DeepEval asks the judge
for a 1-5 score directly; metric.score comes back normalised to 0-1 and
to_1_5() turns it back. HELPFULNESS_RUBRIC is the same text Xu uses for the
human labels in human_labels.csv (Part 3).

Bounded: every Ollama call has a JUDGE_TIMEOUT_S timeout (httpx), DeepEval's own
retries are not used, and score() raises JudgeError instead of hanging.

Smoke test (needs Ollama running):
    python code/eval_pipeline/judge.py
"""

from __future__ import annotations

import os
import time
from typing import Optional

import ollama
from deepeval.metrics import GEval
from deepeval.metrics.g_eval import Rubric
from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, SingleTurnParams

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")   # no usage data leaves the Mac

JUDGE_MODEL = os.getenv("JUDGE_MODEL", "qwen3:4b")
JUDGE_TIMEOUT_S = float(os.getenv("JUDGE_TIMEOUT_S", "90"))
JUDGE_OPTIONS = {"temperature": 0.0, "seed": 9275, "num_ctx": 4096,
                 "num_predict": 300}   # cap: a runaway reply fails fast instead of running on


class JudgeError(RuntimeError):
    """The judge did not return a usable 1-5 score (timeout, Ollama down, bad JSON)."""


class LocalJudge(DeepEvalBaseLLM):
    """DeepEval model wrapper around the local Ollama server."""

    def __init__(self, model: str = JUDGE_MODEL, timeout_s: float = JUDGE_TIMEOUT_S):
        self.timeout_s = timeout_s
        self._client = None
        super().__init__(model)

    def load_model(self):
        if self._client is None:
            self._client = ollama.Client(timeout=self.timeout_s)
        return self._client

    def generate(self, prompt: str, schema=None):
        response = self.load_model().chat(
            model=self.name,
            messages=[{"role": "user", "content": prompt}],
            format=schema.model_json_schema() if schema else None,
            options=JUDGE_OPTIONS,
            think=False,
        )
        text = response.message.content
        return schema.model_validate_json(text) if schema else text

    async def a_generate(self, prompt: str, schema=None):
        return self.generate(prompt, schema)

    def get_model_name(self) -> str:
        return f"{self.name} (Ollama, local)"


def _bands(texts: list[str]) -> list[Rubric]:
    return [Rubric(score_range=(i, i), expected_outcome=t) for i, t in enumerate(texts, 1)]


HELPFULNESS_RUBRIC = [
    "Very poor: does not answer the question, or states values that contradict the "
    "database facts, or invents facts (numbers, names, dates, reasons).",
    "Poor: only partly answers; contains an error or an unsupported claim that could "
    "mislead a store employee.",
    "Acceptable: the requested value is correct, but the answer is vague, padded, or "
    "leaves out something the question asked for.",
    "Good: correct values taken from the facts and a direct answer; small issues such "
    "as extra wording or a minor irrelevant sentence.",
    "Excellent: answers exactly what was asked with the correct values, invents "
    "nothing, concise and immediately useful.",
]

PLAN_RUBRIC = [
    "Very poor: steps are unrelated to the question, or the 'plan' just answers it.",
    "Poor: generic steps that would not lead a writer to the specific answer.",
    "Acceptable: relevant, but misses a key step (e.g. which value to report) or repeats itself.",
    "Good: relevant, ordered steps that cover the question; minor redundancy.",
    "Excellent: clear, specific, ordered steps covering exactly what the question needs.",
]


def plan_quality_metric(judge: Optional[LocalJudge] = None) -> GEval:
    return GEval(
        name="Plan Quality",
        evaluation_steps=[
            "Read the question in 'Input' and decide what a correct answer must contain.",
            "Check whether the steps in 'Actual Output' are about that question and are in a sensible order.",
            "Check whether following the steps would make a writer state the specific value(s) asked for.",
            "Penalise vague or generic steps, repeated steps, and steps that answer instead of plan.",
        ],
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        rubric=_bands(PLAN_RUBRIC),
        model=judge or LocalJudge(),
        async_mode=False,
    )


def helpfulness_metric(judge: Optional[LocalJudge] = None) -> GEval:
    """Used for the Writer draft, the Reviewer final, and the 20 Part 3 drafts."""
    return GEval(
        name="Helpfulness",
        evaluation_steps=[
            "Read the question in 'Input' and the database facts in 'Context'.",
            "Check whether 'Actual Output' directly answers the question with the value(s) asked for.",
            "Compare every number, name, date, and reason in 'Actual Output' with 'Context'; "
            "anything contradicting or not supported by 'Context' is an error.",
            "If 'Context' says the recall does not exist, a helpful answer says so and invents nothing.",
            "Judge usefulness to a store employee: clear, specific, no padding.",
        ],
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT,
                           SingleTurnParams.CONTEXT],
        rubric=_bands(HELPFULNESS_RUBRIC),
        model=judge or LocalJudge(),
        async_mode=False,
    )


def facts_context(facts: Optional[dict]) -> list[str]:
    """The same database facts the Writer and Reviewer saw, as GEval context lines."""
    if not facts:
        return ["No database record was looked up for this question."]
    if facts.get("not_found"):
        return [f"Recall {facts['not_found']} does not exist in the recall database."]
    return [f"{k}: {v}" for k, v in facts.items()]


def to_1_5(normalised: float) -> int:
    return int(round(1 + 4 * normalised))


def score(metric: GEval, question: str, text: str, facts: Optional[dict] = None) -> dict:
    """One judge call -> {"score": 1..5, "reason", "seconds"}; JudgeError on any failure."""
    case = LLMTestCase(input=question, actual_output=text or "(empty)",
                       context=facts_context(facts))
    t0 = time.time()
    try:
        metric.measure(case, _show_indicator=False)
        value = to_1_5(metric.score)
    except Exception as exc:                       # timeout, connection refused, bad JSON ...
        raise JudgeError(f"{type(exc).__name__}: {exc}") from exc
    if not 1 <= value <= 5:
        raise JudgeError(f"score out of range: {metric.score}")
    return {"score": value, "reason": (metric.reason or "").strip(),
            "seconds": round(time.time() - t0, 1)}


if __name__ == "__main__":
    facts = {"recall_number": "F-0002-2021", "product_name": "Green Leaf Almond Granola, 16 oz",
             "units_affected": 6038, "recall_date": "2021-02-25",
             "firm_name": "Maple Snacks Co.", "firm_state": "NV"}
    q = "Which firm issued recall F-0002-2021?"
    good = "Recall F-0002-2021 was issued by Maple Snacks Co., based in Nevada."
    bad = ("Recall F-0002-2021 was issued by Sunrise Foods Inc. because of salmonella "
           "contamination affecting 12,000 units.")
    print(f"judge = {LocalJudge().get_model_name()}  timeout = {JUDGE_TIMEOUT_S}s  options = {JUDGE_OPTIONS}")
    m = helpfulness_metric()
    for label, text in (("good", good), ("bad", bad)):
        r = score(m, q, text, facts)
        print(f"{label:5s} score={r['score']}  {r['seconds']}s  reason={r['reason'][:160]}")
    p = score(plan_quality_metric(), q, "1. Find recall F-0002-2021.\n2. Read the firm name.\n3. Report it.")
    print(f"plan  score={p['score']}  {p['seconds']}s  reason={p['reason'][:160]}")
