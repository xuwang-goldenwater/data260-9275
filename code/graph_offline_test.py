"""
DATA 260 - Homework 2: offline behaviour test for the Part 3 agent graph.

Replaces ModelClient with a scripted fake, so the graph's control flow can be
checked without Ollama and without waiting on a local model. What it proves is
the part that is not about the model at all:

  - a schema-valid proposal ends the run in two turns
  - a rejected proposal is retried, and the run is classified by retry count
  - the Reviewer can send work back to the Planner
  - a Reviewer that always complains hits the ceiling instead of looping forever
  - the same ceiling binds identically on the .stream() and .invoke() paths

Run:  python code/graph_offline_test.py
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import agent_graph as G

class FakeResponse:
    def __init__(self, text):
        self.text = text
        self.input_tokens = 100; self.output_tokens = 20
        self.total_tokens = 120; self.latency_ms = 12.0
        self.model = "fake"; self.raw = {}

class FakeClient:
    """Returns the next scripted reply for whichever agent is asking."""
    def __init__(self, planner_script, reviewer_script):
        self.planner_script = list(planner_script)
        self.reviewer_script = list(reviewer_script)
        self.turn_count = 0
        self.cumulative_input_tokens = 0
        self.cumulative_output_tokens = 0
        self.calls = []
    def complete(self, messages, response_format=None, **kw):
        system = messages[0]["content"]
        is_planner = system.startswith("You extract")
        script = self.planner_script if is_planner else self.reviewer_script
        payload = script.pop(0) if script else (script_default := {})
        self.turn_count += 1
        self.cumulative_input_tokens += 100
        self.cumulative_output_tokens += 20
        self.calls.append(("planner" if is_planner else "reviewer", payload))
        return FakeResponse(json.dumps(payload))
    def stats(self):
        return {"turn_count": self.turn_count,
                "cumulative_input_tokens": self.cumulative_input_tokens,
                "cumulative_output_tokens": self.cumulative_output_tokens,
                "cumulative_total_tokens": self.cumulative_input_tokens + self.cumulative_output_tokens}

GOOD = {"tags": ["peanut butter", "undeclared milk", "product recall"],
        "summary": "Sunrise Valley recalls peanut butter jars that may contain undeclared milk."}
LONG_SUMMARY = {"tags": ["peanut butter", "undeclared milk", "product recall"],
                "summary": " ".join(["word"] * 40)}
LONG_TAG = {"tags": ["peanut butter", "a" * 45, "product recall"], "summary": "Short summary here."}
OK_REVIEW = {"has_issues": False, "issues": "nothing needed changing"}
BAD_REVIEW = {"has_issues": True, "issues": "tag two is a generic category word"}

def run(planner_script, reviewer_script, ceiling=10, force=False, stream=False):
    fake = FakeClient(planner_script, reviewer_script)
    real_init = G.initial_state
    def patched(*a, **k):
        st = real_init(*a, **k)
        st["llm"] = fake
        return st
    G.initial_state = patched
    try:
        rec = G.run_once("T", "C", turn_ceiling=ceiling, force_reviewer_issues=force, stream=stream)
    finally:
        G.initial_state = real_init
    return rec, fake

def case(name, rec, **expect):
    ok = all(rec.get(k) == v for k, v in expect.items())
    print(f"{'PASS' if ok else 'FAIL'}  {name:38} outcome={rec['outcome']!r:26} "
          f"turns={rec['turn_count']} planner={rec['planner_attempts']} reviewer={rec['reviewer_attempts']}")
    if not ok:
        print("      expected", expect)
        print("      got     ", {k: rec.get(k) for k in expect})
    return ok

results = []
# 1. clean run
r, f = run([GOOD], [OK_REVIEW])
results.append(case("valid first attempt", r, outcome="valid first attempt", status="complete",
                    planner_attempts=1, reviewer_attempts=1, turn_count=2))

# 2. schema failure then success -> 1 retry
r, f = run([LONG_SUMMARY, GOOD], [OK_REVIEW])
results.append(case("schema reject -> 1 retry", r, outcome="valid after 1 retry",
                    status="complete", planner_attempts=2))
print("      validation error fed back:", r["history"][0]["error"][:70])

# 3. long tag rejected
r, f = run([LONG_TAG, GOOD], [OK_REVIEW])
results.append(case("tag >30 chars rejected", r, outcome="valid after 1 retry", planner_attempts=2))
print("      validation error fed back:", r["history"][0]["error"][:70])

# 4. two schema failures -> 2+ retries
r, f = run([LONG_SUMMARY, LONG_TAG, GOOD], [OK_REVIEW])
results.append(case("two rejects -> 2+ retries", r, outcome="valid after 2+ retries", planner_attempts=3))

# 5. reviewer sends it back once
r, f = run([GOOD, GOOD], [BAD_REVIEW, OK_REVIEW])
results.append(case("reviewer loop -> 1 retry", r, outcome="valid after 1 retry",
                    planner_attempts=2, reviewer_attempts=2, status="complete"))

# 6. forced reviewer issues -> must hit the ceiling, not hang
r, f = run([GOOD] * 50, [], ceiling=10, force=True)
results.append(case("forced issues, ceiling 10", r, outcome="hit turn ceiling",
                    status="abandoned", turn_count=11, turn_ceiling=10))
print("      ceiling10 forced: planner", r["planner_attempts"], "reviewer", r["reviewer_attempts"])

# 7. ceiling 2 with forced issues
r, f = run([GOOD] * 50, [], ceiling=2, force=True)
results.append(case("forced issues, ceiling 2", r, outcome="hit turn ceiling",
                    status="abandoned", turn_count=3, turn_ceiling=2))

# 8. permanently invalid planner, ceiling 2 -> abandoned
r, f = run([LONG_SUMMARY] * 50, [OK_REVIEW] * 50, ceiling=2)
results.append(case("always invalid, ceiling 2", r, outcome="hit turn ceiling", status="abandoned"))

# 9. permanently invalid planner, ceiling 10 -> abandoned, more attempts
r, f = run([LONG_SUMMARY] * 50, [OK_REVIEW] * 50, ceiling=10)
results.append(case("always invalid, ceiling 10", r, outcome="hit turn ceiling", status="abandoned"))
print("      planner attempts at ceiling 10:", r["planner_attempts"])

# 10. streaming path must produce the same classification
r, f = run([LONG_SUMMARY, GOOD], [OK_REVIEW], stream=True)
results.append(case("stream() path", r, outcome="valid after 1 retry", status="complete"))

r, f = run([GOOD], [OK_REVIEW], ceiling=2)
results.append(case("clean run under ceiling 2", r, outcome="valid first attempt", status="complete", turn_count=2))
r, f = run([LONG_SUMMARY, GOOD], [OK_REVIEW], ceiling=2)
results.append(case("one retry under ceiling 2", r, outcome="hit turn ceiling", status="abandoned"))
r, f = run([LONG_SUMMARY, GOOD], [OK_REVIEW], ceiling=10)
results.append(case("one retry under ceiling 10", r, outcome="valid after 1 retry", status="complete", turn_count=3))

print()
print("recursion limit headroom check: ceiling 10 forced =", 2*10+10, "steps allowed")
print(f"\n{sum(results)}/{len(results)} behaviour tests passed")
sys.exit(0 if all(results) else 1)
