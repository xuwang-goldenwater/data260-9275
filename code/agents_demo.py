"""
DATA 260 - Homework 1, Part 2: two agents that talk to each other.

Pipeline:  Planner -> Reviewer -> Finalizer

The Planner proposes 3 tags and a summary. The Reviewer checks that work
against the same input and corrects it. The Finalizer is deterministic Python
that enforces the hard output contract: exactly 3 tags, summary of at most
25 words, valid JSON.

The agents are domain-agnostic. Nothing in the prompts or the code names a
domain, an industry, or a fixed keyword list. Tags and summary are derived
only from the TITLE and CONTENT that are passed in, which is why the same
script works unchanged on any of the eight assigned domains.

Usage:
    python agents_demo.py
    python agents_demo.py --input ../reports/hw01/cases/nondeterminism_input.json
    python agents_demo.py --temperature 0.7 --quiet
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

# src/model_client.py is the single adapter every model call goes through.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from model_client import ModelClient, DEFAULT_MODEL  # noqa: E402

MAX_SUMMARY_WORDS = 25
TAG_COUNT = 3

# ---------------------------------------------------------------------------
# Output contracts. Ollama enforces these server-side via the `format` field,
# which is far more reliable than asking the model nicely for JSON.
# ---------------------------------------------------------------------------

PLANNER_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": TAG_COUNT,
            "maxItems": TAG_COUNT,
        },
        "summary": {"type": "string"},
        "rationale": {"type": "string"},
    },
    "required": ["tags", "summary"],
}

REVIEWER_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": TAG_COUNT,
            "maxItems": TAG_COUNT,
        },
        "summary": {"type": "string"},
        "changed": {"type": "boolean"},
        "notes": {"type": "string"},
    },
    "required": ["tags", "summary", "changed", "notes"],
}

PLANNER_SYSTEM = (
    "You extract topical metadata from a document.\n"
    "You are given a TITLE and a CONTENT block.\n"
    f"Produce exactly {TAG_COUNT} short topical tags and a summary of at most "
    f"{MAX_SUMMARY_WORDS} words.\n"
    "Rules:\n"
    "- Every tag must be grounded in the given text: use words or phrases that "
    "appear in, or are directly stated by, the TITLE or CONTENT.\n"
    "- Do not use outside knowledge, and do not invent generic category labels.\n"
    "- Tags are 1 to 3 words, lower case, no punctuation, no duplicates.\n"
    "- The summary must be one sentence and factually supported by the CONTENT.\n"
    "Respond with JSON only."
)

REVIEWER_SYSTEM = (
    "You review another agent's extraction against the source text.\n"
    "Check every item:\n"
    f"- exactly {TAG_COUNT} tags, no duplicates and no near-duplicates\n"
    "- each tag is grounded in the TITLE or CONTENT, not outside knowledge\n"
    "- each tag is specific rather than a generic category word\n"
    f"- the summary is at most {MAX_SUMMARY_WORDS} words and is supported by "
    "the CONTENT\n"
    "Return the corrected tags and summary. If the original was already correct, "
    "return it unchanged.\n"
    "Set changed to true only if you altered the tags or the summary.\n"
    "In notes, state in one sentence what you changed and why, or that nothing "
    "needed changing.\n"
    "Respond with JSON only."
)


# ---------------------------------------------------------------------------
# Text cleanup and JSON extraction
# ---------------------------------------------------------------------------

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
CODE_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def strip_model_artifacts(text: str) -> str:
    """Remove reasoning blocks and markdown fences from a raw model reply."""
    text = THINK_BLOCK.sub(" ", str(text))
    fenced = CODE_FENCE.search(text)
    if fenced:
        text = fenced.group(1)
    return text.strip()


def extract_json_object(text: str) -> Dict[str, Any]:
    """Return the first JSON object in text.

    Local models sometimes wrap JSON in prose even when asked not to, so this
    falls back to scanning for a balanced brace pair before giving up.
    """
    cleaned = strip_model_artifacts(text)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = cleaned.find("{", start + 1)

    raise ValueError(f"no JSON object found in model output: {cleaned[:200]!r}")


# ---------------------------------------------------------------------------
# Finalizer: deterministic, no model call
# ---------------------------------------------------------------------------

WORD = re.compile(r"[a-z0-9][a-z0-9\-]*")


def normalize_tag(tag: str) -> str:
    tag = re.sub(r"[^\w\s\-]", " ", str(tag).lower())
    return " ".join(tag.split())


def clamp_summary(summary: str, limit: int = MAX_SUMMARY_WORDS) -> Tuple[str, bool]:
    words = str(summary).split()
    if len(words) <= limit:
        return " ".join(words), False
    return " ".join(words[:limit]), True


def finalize(
    reviewer_tags: List[str],
    reviewer_summary: str,
    fallback_tags: List[str],
) -> Dict[str, Any]:
    """Enforce the output contract without calling the model.

    Deduplicates, normalizes, pads from the Planner's tags if the Reviewer
    returned fewer than three, and truncates the summary to the word limit.
    """
    seen: List[str] = []
    for tag in list(reviewer_tags) + list(fallback_tags):
        norm = normalize_tag(tag)
        if norm and norm not in seen:
            seen.append(norm)
        if len(seen) == TAG_COUNT:
            break

    summary, truncated = clamp_summary(reviewer_summary)

    return {
        "tags": seen,
        "summary": summary,
        "summary_word_count": len(summary.split()),
        "summary_truncated": truncated,
    }


SUFFIXES = ("ing", "ies", "es", "ed", "s")


def stem(word: str) -> str:
    """Strip a common English inflection so word forms compare equal.

    Exact string matching reports a tag as ungrounded when the source text
    uses a different form of the same word: the input says "running" while the
    tag says "run". Trimming one inflectional suffix removes that false
    negative. It is deliberately crude and language-general; it encodes no
    domain vocabulary.
    """
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            base = word[: -len(suffix)]
            if suffix == "ies":
                base += "y"
            return base
    return word


def grounding_report(tags: List[str], title: str, content: str) -> Dict[str, bool]:
    """For each final tag, whether its words actually occur in the input.

    This is a check, not a filter. It is what demonstrates that the tags come
    from the input text rather than from hardcoded domain knowledge.
    """
    source_words = {stem(w) for w in WORD.findall(f"{title} {content}".lower())}
    report: Dict[str, bool] = {}
    for tag in tags:
        tag_words = [stem(w) for w in WORD.findall(tag)]
        report[tag] = bool(tag_words) and all(w in source_words for w in tag_words)
    return report


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def build_input_block(title: str, content: str) -> str:
    return f"TITLE:\n{title}\n\nCONTENT:\n{content}"


def run_pipeline(
    title: str,
    content: str,
    temperature: float = 0.0,
    model: str = DEFAULT_MODEL,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Planner -> Reviewer -> Finalizer. Returns the full record of one run."""
    client = ModelClient(model=model, temperature=temperature)
    input_block = build_input_block(title, content)
    started = time.perf_counter()

    # ---- Agent 1: Planner ----
    planner_response = client.complete(
        messages=[
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": input_block},
        ],
        response_format=PLANNER_SCHEMA,
    )
    planner = extract_json_object(planner_response.text)

    if verbose:
        print("=" * 70)
        print("PLANNER  (agent 1)")
        print("=" * 70)
        print(json.dumps(planner, indent=2, ensure_ascii=False))
        print(
            f"[tokens in={planner_response.input_tokens} "
            f"out={planner_response.output_tokens} "
            f"total={planner_response.total_tokens}  "
            f"latency={planner_response.latency_ms:.0f} ms]\n"
        )

    # ---- Agent 2: Reviewer ----
    reviewer_request = (
        f"{input_block}\n\n"
        "PROPOSED EXTRACTION FROM THE PLANNER:\n"
        + json.dumps(
            {"tags": planner.get("tags", []), "summary": planner.get("summary", "")},
            ensure_ascii=False,
        )
    )
    reviewer_response = client.complete(
        messages=[
            {"role": "system", "content": REVIEWER_SYSTEM},
            {"role": "user", "content": reviewer_request},
        ],
        response_format=REVIEWER_SCHEMA,
    )
    reviewer = extract_json_object(reviewer_response.text)

    if verbose:
        print("=" * 70)
        print("REVIEWER  (agent 2)")
        print("=" * 70)
        print(json.dumps(reviewer, indent=2, ensure_ascii=False))
        print(
            f"[tokens in={reviewer_response.input_tokens} "
            f"out={reviewer_response.output_tokens} "
            f"total={reviewer_response.total_tokens}  "
            f"latency={reviewer_response.latency_ms:.0f} ms]\n"
        )

    # ---- Finalizer: deterministic ----
    final = finalize(
        reviewer_tags=reviewer.get("tags", []),
        reviewer_summary=reviewer.get("summary", planner.get("summary", "")),
        fallback_tags=planner.get("tags", []),
    )
    total_latency_ms = (time.perf_counter() - started) * 1000.0

    publish = {
        "tags": final["tags"],
        "summary": final["summary"],
    }

    record = {
        "publish": publish,
        "planner": planner,
        "reviewer": reviewer,
        "reviewer_changed": bool(reviewer.get("changed", False)),
        "grounding": grounding_report(final["tags"], title, content),
        "summary_word_count": final["summary_word_count"],
        "summary_truncated": final["summary_truncated"],
        "temperature": temperature,
        "model": model,
        "latency_ms": round(total_latency_ms, 1),
        "tokens": {
            "planner_in": planner_response.input_tokens,
            "planner_out": planner_response.output_tokens,
            "reviewer_in": reviewer_response.input_tokens,
            "reviewer_out": reviewer_response.output_tokens,
            "total": planner_response.total_tokens + reviewer_response.total_tokens,
        },
    }

    if verbose:
        print("=" * 70)
        print("FINALIZER  (deterministic, no model call)")
        print("=" * 70)
        print(f"reviewer changed the planner's work : {record['reviewer_changed']}")
        print(f"summary word count                  : {final['summary_word_count']} / {MAX_SUMMARY_WORDS}")
        print("tag grounded in the input text?")
        for tag, ok in record["grounding"].items():
            print(f"    {'yes' if ok else 'no ':>3}  {tag}")
        print()
        print("=" * 70)
        print("PUBLISH")
        print("=" * 70)
        print(json.dumps(publish, indent=2, ensure_ascii=False))
        print(f"\ntotal latency: {record['latency_ms']:.0f} ms")

    return record


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

DEFAULT_TITLE = "Sunrise Valley Creamy Peanut Butter, 16 oz jar"
DEFAULT_CONTENT = (
    "Sunrise Valley Foods is voluntarily recalling 16 oz jars of Creamy Peanut "
    "Butter with lot codes SV2451 through SV2458 and best-by dates from "
    "2027-03-11 to 2027-03-18. Routine internal testing found the affected lots "
    "may contain undeclared milk from a shared production line. People with an "
    "allergy or severe sensitivity to milk risk a serious or life-threatening "
    "allergic reaction. The product was distributed to retail stores in "
    "California, Nevada, and Oregon. Consumers should not eat the product and "
    "may return it to the place of purchase for a full refund."
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Planner / Reviewer / Finalizer demo")
    parser.add_argument("--title", default=None, help="entity title")
    parser.add_argument("--content", default=None, help="entity content")
    parser.add_argument(
        "--input", default=None, help="path to a JSON file with title and content"
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--quiet", action="store_true", help="print only the final Publish JSON"
    )
    args = parser.parse_args()

    if args.input:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        title = data.get("title") or data.get("productName") or DEFAULT_TITLE
        content = data.get("content") or data.get("description") or DEFAULT_CONTENT
    else:
        title = args.title or DEFAULT_TITLE
        content = args.content or DEFAULT_CONTENT

    try:
        record = run_pipeline(
            title=title,
            content=content,
            temperature=args.temperature,
            model=args.model,
            verbose=not args.quiet,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"pipeline failed: {exc}", file=sys.stderr)
        return 1

    if args.quiet:
        print(json.dumps(record["publish"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
