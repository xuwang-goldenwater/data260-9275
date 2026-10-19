# HW6 AI_USE — Xu Wang

**1. What I used an AI assistant for, and what I did myself.**
I used Claude (Anthropic) as a coding assistant. Because of time, it wrote the first version of
most code (the MongoDB document API, the memory logic). It proposed the designs and I chose among the
options: the qwen2.5:3b model (after timing it on my M1), extending AGENT.md in place, the
consolidation trap, and the rule for the best Part 3 setting. I ran every command on my Mac, hand-scored all 20
probe answers against my own rubric, checked the AGENT.md compliance table, and reviewed
each result before it was committed.
I drafted METRICS.md and it modified that. 
I drafted Part3 and Part4 codes and it debugged for me.

**2. One AI-produced output that was wrong.**
The first fact-extraction code in Part 2 poisoned the episodic memory. After the 12-message
test conversation it had stored 21 facts, including "User has a tree nut allergy." with
importance 1.0 (it was my daughter, not me) and facts I never said ("User usually shops at
Walmart", "User lives in New York City"), extracted from my questions. The assistant then
answered "you also have a tree nut allergy".

**3. How I detected it.**
The reply to "Who in my family has an allergy?" was wrong, so I queried the `episodes` and
`summaries` collections in MongoDB and compared every stored fact with what I had typed
(saved as `raw/part2_run1_poisoned_memory.json`). The summaries were also wrong: they were
about Listeria and canned fish, because they summarised the assistant's own answers.

**4. What I changed and why it works now.**
Question sentences are removed before extraction, a fact is kept only if most of its words
appear in my message, the prompt requires facts to name the right person (with an example),
and summaries read only my own messages. Re-running the same 12 messages stored 8 facts, none
invented and none attributed to the wrong person. A wrong attribution can still pass the word
check, so that guard depends on the prompt.
