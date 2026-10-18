"""HW6 Part 4: chat with file-based memory (AGENT.md + MEMORY.md) and memory commands.

    python code/file_memory_cli.py                       interactive
    python code/file_memory_cli.py --run "/compact"      run one command and exit (evidence)
    python code/file_memory_cli.py --memory PATH         use another MEMORY.md (tests)

Commands
    /memory   show the current file-based memory and whether it needs consolidation
    /compact  consolidate MEMORY.md; prints line and fact counts before and after
    /dream    add durable facts from recent conversation to MEMORY.md
    /help     list the commands
    /quit     leave
Anything else is a chat message; the system prompt is AGENT.md + MEMORY.md.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import file_memory as fm  # noqa: E402

HELP = """Commands:
  /memory   show AGENT.md size and the full MEMORY.md, plus whether consolidation is due
  /compact  consolidate MEMORY.md (merge duplicates, resolve contradictions explicitly)
            and report the line/fact counts before and after
  /dream    find durable facts in this session's messages (or, if none yet, the last
            messages stored in MongoDB for --user) and append them to MEMORY.md
  /help     this list
  /quit     exit
Any other input is sent to the model with AGENT.md + MEMORY.md as the system prompt."""


class FileMemorySession:
    def __init__(self, memory_path: Path, agent_path: Path, user_id: str) -> None:
        self.memory_path = memory_path
        self.agent_path = agent_path
        self.user_id = user_id
        self.history = []              # this session's chat, for replies and /dream

    # ---- commands
    def cmd_memory(self) -> str:
        agent, mem = fm.load_memory_files(self.agent_path, self.memory_path)
        due, reasons = fm.needs_consolidation(mem)
        last = fm.read_last_consolidated(mem)
        return (f"AGENT.md: {len(agent.splitlines())} lines | MEMORY.md ({self.memory_path.name}): "
                f"{fm.count_memory_lines(mem)} counted lines, {len(fm.fact_lines(mem))} facts | "
                f"last consolidated: {last.isoformat() if last else 'never'}\n"
                f"consolidation due: {'yes - ' + '; '.join(reasons) if due else 'no'}\n"
                f"{'-' * 60}\n{mem.strip() or '(empty)'}")

    def cmd_compact(self) -> str:
        _, mem = fm.load_memory_files(self.agent_path, self.memory_path)
        new_text, rep = fm.consolidate(mem)
        self.memory_path.write_text(new_text, encoding="utf-8")
        report_path = self.memory_path.with_suffix(".compact_report.json")
        report_path.write_text(json.dumps(rep.as_dict(), indent=2), encoding="utf-8")
        lines = [f"/compact: {rep.lines_before} lines -> {rep.lines_after} lines; "
                 f"{rep.facts_before} facts -> {rep.facts_after} facts "
                 f"({'under' if rep.lines_after < fm.MAX_MEMORY_LINES else 'NOT under'} "
                 f"{fm.MAX_MEMORY_LINES})",
                 f"  duplicate groups merged: {len(rep.duplicates_merged)}",
                 f"  contradictions resolved: {len(rep.contradictions_resolved)}",
                 f"  silently deleted lines: {rep.not_accounted or 'none'}"]
        if rep.plan_errors:
            lines.append(f"  plan entries rejected: {rep.plan_errors}")
        lines.append(f"  report: {report_path.name}")
        return "\n".join(lines)

    def cmd_dream(self) -> str:
        msgs = [m["content"] for m in self.history if m["role"] == "user"]
        source = "this session"
        if not msgs:
            import memory as chat_memory
            recent = chat_memory.load_short_term_any(self.user_id, 16)
            msgs = [m["content"] for m in recent if m["role"] == "user"]
            source = f"MongoDB messages of {self.user_id}"
        if not msgs:
            return "/dream: no recent messages to learn from."
        _, mem = fm.load_memory_files(self.agent_path, self.memory_path)
        new = fm.dream(msgs, mem)
        if new:
            fm.append_lines(self.memory_path, new)
        return (f"/dream: read {len(msgs)} user message(s) from {source}; "
                f"added {len(new)} fact(s)" + "".join(f"\n  {ln}" for ln in new))

    # ---- chat
    def chat(self, text: str) -> str:
        import memory as chat_memory
        agent, mem = fm.load_memory_files(self.agent_path, self.memory_path)
        messages = [{"role": "system", "content": fm.build_system_prompt(agent, mem)}]
        messages += self.history[-10:] + [{"role": "user", "content": text}]
        resp = chat_memory.get_model().complete(messages, max_tokens=400)
        self.history += [{"role": "user", "content": text},
                         {"role": "assistant", "content": resp.text.strip()}]
        return f"{resp.text.strip()}\n  [{resp.input_tokens} prompt tokens, {resp.latency_ms / 1000:.1f} s]"

    def handle(self, line: str) -> str:
        line = line.strip()
        commands = {"/memory": self.cmd_memory, "/compact": self.cmd_compact,
                    "/dream": self.cmd_dream, "/help": lambda: HELP}
        if line in commands:
            return commands[line]()
        if line.startswith("/"):
            return f"unknown command {line!r}\n{HELP}"
        return self.chat(line)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--memory", type=Path, default=fm.MEMORY_PATH)
    ap.add_argument("--agent", type=Path, default=fm.AGENT_PATH)
    ap.add_argument("--user", default="xu_wang", help="MongoDB user for /dream fallback")
    ap.add_argument("--run", action="append", default=[], help="command or message to run, then exit")
    args = ap.parse_args()
    session = FileMemorySession(args.memory, args.agent, args.user)
    print(f"Xu Wang | DATA 260 HW6 Part 4 | file memory | {datetime.now():%Y-%m-%d %H:%M:%S} "
          f"| memory={args.memory.name}")
    _, mem = fm.load_memory_files(args.agent, args.memory)
    due, reasons = fm.needs_consolidation(mem)
    if due:
        print(f"[note] MEMORY.md needs consolidation ({'; '.join(reasons)}); run /compact")
    if args.run:
        for item in args.run:
            print(f"\n> {item}\n{session.handle(item)}")
        return
    print("type /help for commands")
    while True:
        try:
            line = input("\n> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if line.strip() in {"/quit", "/exit"}:
            break
        if line.strip():
            print(session.handle(line))


if __name__ == "__main__":
    main()
