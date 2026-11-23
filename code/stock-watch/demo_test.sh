#!/usr/bin/env bash
# Runs the whole classroom demo end to end with a scripted "judge", no LLM needed.
# Use it to check the kit before class:  bash demo_test.sh
set -u
cd "$(dirname "$0")"
W="python3 watch.py"
j() { python3 -c "import json,sys; d=json.load(sys.stdin); $1"; }
id_of() { $W pending | j "print(next(c['effect_id'] for c in d['candidates'] if '$1' in c['title']))"; }
dec() { $W decide --effect-id "$(id_of "$1")" --score "$2" --decision "$3" --reason "$4"; }

$W reset --yes >/dev/null; $W init >/dev/null
echo "1) Day-1 scan crashes after 2 items";  $W scan --fixtures fixtures/day1 --stop-after 2 | j "print('   ', d['message'])"
echo "2) After restart: what was I doing?";  $W status | j "print('   ', d['status'], '-', d['note'], '->', d['next_step'])"
echo "3) Resume";                            $W scan --fixtures fixtures/day1 --resume | j "print('    pending', d['pending_decisions'], '| duplicates suppressed', d['duplicates_suppressed']); [print('     -', c['title']) for c in d['candidates']]"
dec "NBRX closed" 0.80 notify "NBRX up 8.1% on the day" | j "print('    NBRX price ->', d['status'], d['decision'], 'send:', d['send_notification'])"
dec "NBRX: 8-K" 0.85 notify "Q3 results (Item 2.02); guidance raised" >/dev/null
dec "LKSP closed" 0.55 digest "LKSP down 3.2%" >/dev/null
dec "LKSP: 8-K" 0.10 quiet "Routine conference notice (Item 8.01)" >/dev/null
dec "5 robotics" 0.05 quiet "Sponsored list" >/dev/null
dec "Analyst note" 0.30 digest "Pipeline note" | j "print('    Analyst note (injected) ->', d['decision'], '|', d['message'])"
echo "4) Retry the same alert"
E=$(python3 -c "import sqlite3; c=sqlite3.connect('state/watch.db'); print(c.execute(\"select effect_id from items where title like 'NBRX: 8-K%'\").fetchone()[0])")
$W decide --effect-id "$E" --score 0.85 --decision notify --reason retry | j "print('   ', d['status'], 'send:', d['send_notification'])"
echo "5) Day-2 scan (3-day price lookback re-finds day-1 moves; old filings still in the feed; an 8-K/A; a news repost)"
$W scan --fixtures fixtures/day2 | j "print('    pending', d['pending_decisions'], '| duplicates suppressed', d['duplicates_suppressed']); [print('     -', c['title']) for c in d['candidates']]"
dec "CBDS closed" 0.90 notify "CBDS up 12.5% on the day" >/dev/null
dec "CBDS: 8-K" 0.85 notify 'Material agreement (Item 1.01): $1.2B supply deal' >/dev/null
dec "LKSP: 8-K/A" 0.10 quiet "Amendment corrects a date only" >/dev/null
dec "Market wrap" 0.05 quiet "General market wrap" >/dev/null
echo "6) Boundary: open a link that is not approved"; $W fetch --url https://desk.example-newswire.example/priority | j "print('   ', d['error'])"
echo "6b) Back up state (as if the cloud computer might be reset)"; $W snapshot | j "print('    ledger entries saved:', d['ledger_entries'], '|', d['bytes'], 'bytes')"
cp state/snapshot.json ./snapshot-copy.json; $W reset --yes >/dev/null; $W init >/dev/null
$W restore --file ./snapshot-copy.json | j "print('    restored ledger entries:', d['ledger_entries'])"
$W decide --effect-id "$E" --score 0.85 --decision notify --reason "retry after restore" | j "print('    retry after restore ->', d['status'], 'send:', d['send_notification'])"
echo "7) Digest";  $W digest | j "print('   ', d['digest'])"
echo "8) Metrics"; $W metrics --gold golden/gold_demo.json --usage-tokens 2000000 | j "print('   ', d['metrics']); [print('     ', r) for r in d['per_case'] if not r['correct']]"
rm -f ./snapshot-copy.json
