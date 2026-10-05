# AI use - Homework 5

## 1. What I used an AI assistant for, and what I did myself

**AI assistant (Claude):**

- Explained the assignment and put the steps in order.
- Review the design and give me advice and options to choose.
- Wrote the first version of the code for each part: the migration script, the
  firms/notices API, the Redux client, the two MCP servers, the retry policy,
  the fault-injection experiment, `execute_tool`, the offline tests and the
  agent loop. It tested these in its own environment before handing them over.
- Read the output and logs I pasted back and diagnosed problems.
- Review my reflection and put my reflection into English.

**Me:**

- First designed the whole structure and ask AI to modify my ideas
- Made these design decisions: `contact_email` and `recall_number` as the unique
  fields; a migration script instead of rebuilding the tables; the safety rule
  (no ranking of named firms by recalls).
- Reviewed and approved the retry-policy numbers and the design of the three
  domain tools that the assistant proposed.
- Ran all the code on my Mac (MySQL, conda env `data260`, Ollama `qwen3:8b`) and
  compared each output with what was expected.
- Tested every tool by hand in the MCP Inspector web UI and took the Inspector,
  Postman, database and React screenshots.
- Found several places where the result did not match what the assistant had
  told me (one is described below).
- Drafted the analysis text in `METRICS.md` and wrote my reflection in Chinese.

## 2. One AI-produced output that was wrong

For the invalid-input test in Part 2A, the assistant told me to type `limit = 99`
into the Inspector form for `search_meals_by_name` (allowed range 1-25) and said
I would see a validation error. I did that and got no error. The tool ran and
returned meals as if the input were valid.

## 3. How I detected the problem

I ran the call in the Inspector web UI and looked at the result panel: no error
message, a normal list of meals. I reported this to the assistant with a
screenshot. The cause was the Inspector (version 2.9), not my server. Its form
reads `maximum: 25` from the tool schema and silently changes 99 to 25 when the
input box loses focus, so the value 99 was never sent to the server.

## 4. What I changed and why it works now

- In the web UI I now enter invalid values with "Edit as JSON", which sends the
  arguments exactly as typed.
- `code/mcp_capture.py` (`make capture-meals`) sends the same call through the
  Inspector command-line mode, which does not change the arguments.

It works because the raw value now reaches the server.
`raw/mcp_inspector_meals.json` records the call with `"limit": 99` and the
server's answer: `isError: true`, "Input should be less than or equal to 25".
What I took from this: a tool's input check is tested only if the invalid value
is really sent, so I check what the client sent, not only what I typed.
