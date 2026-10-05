# HW5 Reflection

Xu Wang | SID4 9275 | run `3adaf676` in `raw/agent_runs.jsonl` (qwen3:8b, max_steps 5)

A harmless question: "Find the most recent peanut butter recall and tell
me which firm issued it and that firm's contact email."

**Step 1.** The harness sent the system prompt, the question and the three tool
schemas to the model. The model asked for
`search_notices(query="peanut butter", limit=1)`. The harness passed the call to
`execute_tool`. The safety check found nothing, the query ran, and the envelope
came back `ok: true` with notice `F-4906-2026`. The harness added the result
to the conversation.

**Step 2.** The model should have called `get_notice`, which returns the firm's
email. It called `recall_summary(group_by="firm", year=2026)` instead. My safety
rule forbids grouping by firm, because the assistant must not rank named
companies by recalls. `execute_tool` returned `ok: false` with a "blocked by
safety rule" error and ran no query.

**Why it stopped.** A safety-rule block. The harness recognised the block, ended
the loop at once and wrote the refusal itself, after 2 of 5 steps and 2 tool
calls. The model was not called again.

**What I learned.** The rule did its job, but the system was fragile: a block is
final, so one wrong tool choice cost the user a legitimate answer. I did not
loosen the rule. I rewrote the tool descriptions and the system prompt to say
that `get_notice` returns the firm and its email and that `recall_summary` is
for statistics only. In the next batch the same question completed in 3 steps
(run `52422676`). A further option is to return a block to the model as an
ordinary error, so it can try another tool within `max_steps`, as the loop
already does for invalid inputs. A strict rule is not enough. The tool
descriptions must also guide the model to the right tool.
