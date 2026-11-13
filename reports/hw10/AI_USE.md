# HW10 AI_USE — Xu Wang

**1. What I used an AI assistant for, and what I did myself.**

I used Claude (Anthropic) as a coding assistant.
For each part, Claude proposed a design (the trace_id created before the cache lookup and reused as the Kafka correlation_id, one JSON span per stage in a shared file, queue wait from the Kafka CreateTime, a separate evaluator consumer that joins plan / draft / final on correlation_id, a local judge with a 1-5 rubric, a serial 50-request miss experiment, a dashboard that only reads saved evidence); I reviewed each proposal and approved it before any code was written.
I first wrote the code file by file and drafted METRICS.md and this report; Claude reviewed every file and edited the report.
I chose to keep the judge rubric unchanged after the smoke test, hand-assigned the 20 helpfulness labels from the labelling sheet and committed them before the validation script existed, ran every command on my Mac (Kafka, Redis, MySQL, Ollama, the three agent terminals and the evaluator, the latency run, the trace examples, the judge validation, the dashboard and the self-check), took every screenshot, and checked each result before committing.


**2. One AI-produced output that was wrong.**

The HW9 gateway code (written by Claude) waited for Kafka without a limit. In `SemanticCache.run_agent()` the gateway consumer joined the `s9275_final` topic with `while not consumer.assignment(): consumer.poll(0.2)`. When Kafka is not running, no partition is ever assigned, so the request hangs forever - exactly what HW10 Part 2.1 says the system must not do.

**3. How I detected it.**

While testing the new trace_id on a cache hit, my test question turned out to be a stale cache entry (miss_reason "stale") and went to the agent path while Kafka was not started. The terminal printed `Connect to ipv4#127.0.0.1:9092 failed: Connection refused` without end and never returned. I pasted the output; the span file showed the cache_lookup and facts_lookup spans but no gateway span, because the request never finished.

**4. What I changed and why it works now.**

The join now has a 30 s deadline: if no partition is assigned in time the gateway closes the consumer and raises `ConnectionError`, and the gateway span records it as `status = error`. The evaluator got the same 30 s limit, and `tracing.span()` now catches `BaseException`, so even a Ctrl+C leaves an error span. Later, in the first 50-request run, the gateway consumer was dropped after 300 s without `poll()` (MAXPOLL) while the script waited for the evaluator; its `max.poll.interval.ms` is now 1 hour. The failed-trace example (Part 4.2) and the self-check show that a failure now ends with an error span instead of a hang.

A second AI error is reported in the results rather than fixed: the judge context Claude wrote for questions without a database record ("No database record was looked up") made the judge treat correct off-domain answers as invented (Part 3). I found it by reading the judge's reasons after validation; I did not change the judge, because tuning it on the same 20 labelled drafts would invalidate the validation.
