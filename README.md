# data260-9275

DATA 260 coursework repository. Application code is shared across all homework
assignments; per-assignment evidence lives under `reports/hwNN/`.

**Repository:** https://github.com/xuwang-goldenwater/data260-9275

## Layout

```
code/                  shared application code (extended each homework)
  web_application/     web app source
  agents_demo.py       agent demo entrypoint
  hw1_client.py        HW1 driver script
  Dockerfile           container image for the application
src/
  model_client.py      model adapter (required exact path)
reports/
  hw01/                HW1 report, metrics, logs, raw outputs
  hw02/ hw03/          future assignments
AGENT.md               agent design, tools, prompts
DOMAIN_SCHEMA.md       domain data schema
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then fill in your API key
python code/hw1_client.py --help
```

## Collaborators

- Sbnikitha
- supriyaselvanganesan

## Conventions

- Do **not** copy application code into `reports/`. Reports hold evidence only.
- The model adapter must stay at `src/model_client.py`.

## Homework 1 — Part 4 conceptual answers

Measured in one five-turn session with `qwen3:8b` at temperature 0.0, system
prompt `AGENT.md` (1,212 characters). Full transcript in
`reports/hw01/RUN_LOG.txt`.

| Turn | Input tokens | Output tokens | Latency (ms) |
|---|---|---|---|
| 1 | 344 | 25 | 17,715 |
| 2 | 463 | 101 | 12,289 |
| 3 | 622 | 118 | 16,385 |
| 4 | 774 | 35 | 5,480 |
| 5 | 834 | 244 | 24,959 |
| **Total** | **3,037** | **523** | — |

Serialized history: 3,359 characters after turn 3, 5,030 after turn 5.

### Why is prior conversation context resent with every turn?

Because the model holds no state between calls. Each request is independent;
the server keeps nothing from the previous one. Anything the model needs to
know has to be inside the request.

Turn 4 shows this directly. The question was 108 characters — roughly 25
tokens — but the turn billed 774 input tokens. The other ~750 were the earlier
conversation being replayed. That replay is what let the model answer "of the
three functions I have shown you so far" correctly; with only the 25-token
question it would have had no idea which three functions were meant.

This is the same statelessness that REST requires of a web service: the server
does not remember the client, so the client carries the context.

### How is a system prompt different from a user message?

Three ways, all visible in this session.

- **Position and persistence.** The system prompt is message index 0 and is
  resent unchanged on every turn. User messages accumulate behind it.
- **Purpose.** It sets standing rules for how to answer, rather than asking a
  question to be answered. `AGENT.md` never asks for anything; it constrains
  the shape of every reply.
- **Cost.** Its 1,212 characters were billed in all five turns. A system prompt
  is a fixed tax on every request, not a one-time setup cost.

It is not, however, an enforcement mechanism. On turn 5 the model produced 13
bullets when `AGENT.md` caps replies at 6, because the user's request ("list
every defect across the conversation") conflicted with the cap and the model
chose the request. A system prompt is a strong prior, not a constraint — which
is why `hw1_client.py` checks compliance in code rather than assuming it.

### Why do input tokens grow over a conversation?

Every turn sends the system prompt, every previous user message, every previous
assistant reply, and the new message. Nothing is ever removed, so the request
gets longer each time: 344 → 463 → 622 → 774 → 834.

Each increase tracks what was added since the last turn. Input rose 159 tokens
from turn 2 to turn 3, and turn 2's reply was 101 tokens plus the new question.

The cumulative effect is lopsided: 3,037 input tokens against 523 output
tokens. **85% of everything processed was input, and most of that was history
being re-read.** Because turn *n* carries everything before it, total tokens
over a conversation grow roughly with the square of the turn count, not
linearly.

### What eventually limits that growth?

The context window — the maximum number of tokens the model can accept in one
request. Once history plus the new message exceeds it, the request either fails
or the oldest messages are silently dropped, and the model forgets the start of
the conversation without saying so.

For this setup, `ollama show qwen3:8b` reports a context length of **40,960
tokens**. Input reached 834 tokens by turn 5 and grew by roughly 120-150 tokens
per turn, that growth being the previous reply plus the new question. At that
rate the window fills somewhere around turn 300. The effective ceiling can be
lower still: the running server's `num_ctx` may be set below what the model
supports, and whichever number is smaller is the one that applies.

Before that hard ceiling, cost and latency bite first. Two practical notes from
this session's timings:

- Latency tracks **output** tokens, not input. Turn 4 read 774 input tokens and
  finished in 5.5 s because it wrote only 35 tokens; turn 5 read a similar 834
  and took 25.0 s because it wrote 244. Input is processed in one parallel
  prefill pass; output is generated one token at a time.
- Input is therefore cheap per token but grows without bound, which is what
  later techniques address: trimming or summarising old turns, retrieving only
  relevant history instead of all of it, and caching the unchanged prefix so
  the same prefill is not paid for repeatedly.
