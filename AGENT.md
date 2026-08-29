# AGENT.md

> Scaffold — fill in from the Homework 1 instructions.

## Purpose

What the agent does and the task it is evaluated on.

## Architecture

| Component | File | Responsibility |
|---|---|---|
| Model adapter | `src/model_client.py` | Uniform interface to the LLM provider |
| Agent loop | `code/agents_demo.py` | Planning, tool dispatch, termination |
| HW1 driver | `code/hw1_client.py` | Runs the assignment tasks, writes raw output |
| Web app | `code/web_application/` | User-facing interface |

## Tools

| Tool | Input | Output | Notes |
|---|---|---|---|
| _TODO_ | | | |

## System prompt

```text
TODO
```

## Termination and guardrails

- Max steps: TODO
- Failure handling: TODO
