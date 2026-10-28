# HW8 AI_USE — Xu Wang

**1. What I used an AI assistant for, and what I did myself.**

I used Claude (Anthropic) as a coding assistant. 
I summarized the assignment into concrete tasks, proposed the design (one compose stack for Kafka + worker + FastAPI, a growing JSON message for the three agents, one switch per Part 3 fix so each "before" run changes only one thing).
It wrote the framework of code one file at a time: the RecallNotice worker and FastAPI wrapper, homework_demo.py, the Planner, Writer and Reviewer, the reliability helpers, the Part 3 test tool.
I filled up the core parts of each file.
I ran every command on my Mac (Docker, the four agent terminals, every before/after failure run), chose to run the consumer-death test by hand, step by step, instead of an automated script, took every screenshot, and checked each result against the expected output before committing.


**2. One AI-produced output that was wrong.**

The first Writer prompt asked the model to answer "covering each step of the plan in order".
qwen2.5:3b answered by copying the three plan lines word for word, and the Reviewer (also the
model) approved it, so the first end-to-end run delivered `"status": "approved"` with an answer
that answered nothing.

**3. How I detected it.**

I read the final JSON from `s9275_final` for the first test message (`plan-test-1`): the `draft`
and `answer` fields were identical to the `plan` list, and the review reason was "The draft
follows the plan and answers the question". The pipeline "worked"; only reading the content
showed the failure.

**4. What I changed and why it works now.**

Two changes. The Writer prompt now asks for one paragraph of 3–5 full sentences, uses the plan only
as an outline and forbids copying the plan lines or a numbered list. The Reviewer got a
deterministic rule that runs before the model: if the draft's normalized text is ≥ 0.8 similar to
the plan (difflib), it is rejected. The copied draft scores 1.00 and is rejected; the next runs
produced 53- and 85-word answers that pass the rule and were approved. verify_hw08.py checks both
cases, so the rule cannot silently disappear.

A second issue I verified independently: after the compose file changed, Docker recreated the
Kafka container and every topic was gone, which made homework_demo.py fail with "no partition
assignment". Listing the topics confirmed it; the fix is the `kafka-init` service, which recreates
all seven topics before the worker and API start.
