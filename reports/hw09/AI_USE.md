# HW9 AI_USE — Xu Wang

**1. What I used an AI assistant for, and what I did myself.**

I used Claude (Anthropic) as a coding assistant.
For each part, Claude proposed a design (where the cache sits in front of the HW8 pipeline, a frozen-cache sweep with one real agent run per case, a per-record version number for invalidation, a deterministic Evaluator and a validation gate for lessons); I reviewed each proposal and approved it before any code was written.
Claude drafted cache_cases.yaml from the database records I pulled, and I wrote METRICS.md and this report.
I decided the labels in cache_cases.yaml before any sweep ran, accepted the cost model (miss = 1, false hit = 20) and the shipped threshold, ran every command on my Mac (Redis, MySQL, Kafka and the three agent terminals, every demo, sweep and Part 4 run), took every screenshot, and checked each result before committing.


**2. One AI-produced output that was wrong.**

The first version of the Evaluator Agent (written by Claude) passed an answer that should have failed. For the off-domain training question train_07 "How long should I boil an egg?", the revised answer was: "I can only provide information about grocery recall notices. For your question about how long to boil an egg, the general recommendation is to boil an egg for about 7-10 minutes." The rule only checked that a decline phrase appeared somewhere, so it returned PASS — the agent declined and answered anyway, and the Evaluator rewarded it. Because lessons are built from the Evaluator's verdicts, this would have taught the system that "decline, then answer" is correct.

**3. How I detected it.**

After the first training run I could not find the NEW LESSON line in the summary and asked about it. To check, Claude printed every attempt from results/train.json instead of the summary, and the attempt-2 text for train_07 still contained the boiling time while its verdict was PASS. I confirmed it by reading the answer myself. (That run is kept as part4/results/train_run1_evaluator_bug.json.)

**4. What I changed and why it works now.**

The off-domain rule now checks every sentence: each one must either decline or be about recall notices; any other sentence means the question was answered. Two new self-test cases cover it (decline + answer -> REVISE; decline + "unrelated to that topic" -> PASS), and verify_hw09.py re-checks the decline-then-answer case. Re-running training on the same data gave train_07 REVISE after two attempts, which is the correct result, and the failure count that created lesson_001 did not change.

The Evaluator was wrong twice more, in the other direction: in validation it rejected a correct not-found answer ("does not contain any recall notice", fixed before the test run), and in the test run it rejected a correct decline ("not relevant to this database"). The test result was not used to change the system; it is reported as measured, with the manual review written next to the table in METRICS.md.
