"""
DATA 260 - HW10 Part 1: Streamlit operations dashboard for the HW8/HW9 pipeline.

An evidence viewer, not a new application: every number is read from files the
system itself wrote, and each metric says which file and which time window it uses.

    Summary       requests, cache hit rate (hits vs misses), error rate, end-to-end
                  latency (cache-miss and cache-hit kept separate), stage-latency table
    Evaluation    Part 2 scores by stage and case, Part 3 judge validation, interpretation
    Trace lookup  one trace_id -> every span in stage order, hit / miss / failed path

Data (all under reports/hw10/):
    raw/spans.jsonl           HW10_SPANS - one line per span (gateway, agents, evaluator)
    raw/eval_results.jsonl    Part 2 evaluator output
    raw/latency_summary.json  Part 4.3 table (latency_experiment.py analyze)
    raw/trace_examples.json   Part 4.2 hit / miss / failed trace ids
    part3/judge_runs.csv, part3/judge_validation.json   Part 3
Live: Redis (number of entries in the semantic cache), optional.

    streamlit run code/ops_dashboard/app.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "reports/hw10/raw"
PART3 = ROOT / "reports/hw10/part3"
SPANS = Path(os.getenv("HW10_SPANS", RAW / "spans.jsonl"))
EVAL = RAW / "eval_results.jsonl"
LATENCY = RAW / "latency_summary.json"
EXAMPLES = RAW / "trace_examples.json"
QUESTIONS = RAW / "latency_questions.json"
STAGE_ORDER = ["gateway", "cache_lookup", "facts_lookup", "queue_wait", "planner", "writer",
               "reviewer", "evaluation"]


# ------------------------------------------------------------------ data access
def _mtime(p: Path) -> float:
    return p.stat().st_mtime if p.exists() else 0.0


@st.cache_data(ttl=30, show_spinner=False)
def read_jsonl(path: str, mtime: float) -> list[dict]:
    """Cached per file version: re-read only when the file changes (or after 30 s)."""
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


@st.cache_data(show_spinner=False)
def read_json(path: str, mtime: float):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else None


@st.cache_data(show_spinner=False)
def read_csv(path: str, mtime: float) -> pd.DataFrame:
    p = Path(path)
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_resource(show_spinner=False)
def redis_client():
    """One Redis connection for the whole app (a reusable resource, not data)."""
    import redis
    r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                             decode_responses=True, socket_connect_timeout=1)
    r.ping()
    return r


def spans_df() -> pd.DataFrame:
    df = pd.DataFrame(read_jsonl(str(SPANS), _mtime(SPANS)))
    if df.empty:
        return df
    df["start"] = pd.to_datetime(df["start_ts"])
    df["end"] = pd.to_datetime(df["end_ts"])
    return df


def evals() -> list[dict]:
    return read_jsonl(str(EVAL), _mtime(EVAL))


def kinds() -> dict:
    q = read_json(str(QUESTIONS), _mtime(QUESTIONS))
    return {x["trace_id"]: x["kind"] for x in q["questions"]} if q else {}


def pct(s: pd.Series, p: int) -> str:
    return "–" if s.empty else f"{s.quantile(p / 100):,.0f} ms"


def source(text: str) -> None:
    st.caption(f"Source: {text}")


# ------------------------------------------------------------------ 1.1 Summary
def summary_page() -> None:
    st.title("Operations summary")
    df = spans_df()
    if df.empty:
        st.warning(f"No spans yet in {SPANS}")
        return
    choice = st.radio("Time window", ["All recorded", "Last 1 hour", "Last 24 hours", "Last 7 days"],
                      horizontal=True)
    gw = df[df["stage"] == "gateway"].copy()
    now = datetime.now()
    if choice != "All recorded":
        delta = {"Last 1 hour": timedelta(hours=1), "Last 24 hours": timedelta(days=1),
                 "Last 7 days": timedelta(days=7)}[choice]
        gw = gw[gw["start"] >= now - delta]
    if gw.empty:
        st.info("No requests in this window.")
        return
    window = f"{gw['start'].min():%Y-%m-%d %H:%M} → {gw['end'].max():%Y-%m-%d %H:%M} ({choice.lower()})"
    gw_src = f"`{SPANS.relative_to(ROOT)}`, stage = gateway (one span per request); window {window}"

    hits, misses = gw[gw["cache"] == "hit"], gw[gw["cache"] != "hit"]
    errors = gw[gw["status"] == "error"]
    rejected = misses[misses.get("outcome", pd.Series(dtype=str)) == "rejected"] \
        if "outcome" in misses else misses.iloc[0:0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Requests", len(gw))
    c2.metric("Cache hit rate", f"{len(hits) / len(gw):.1%}", help="hits / all requests")
    c3.metric("Error rate", f"{len(errors) / len(gw):.1%}",
              help="gateway span status=error: exception or timeout anywhere on the path")
    c4.metric("Reviewer rejection rate", f"{len(rejected) / max(1, len(misses)):.1%}",
              help="answer outcome, not a system error: rejected / cache misses")
    source(gw_src)

    a, b = st.columns(2)
    with a:
        st.subheader("Cache hits vs misses")
        counts = pd.DataFrame({"path": ["cache hit", "cache miss"], "requests": [len(hits), len(misses)]})
        st.altair_chart(alt.Chart(counts).mark_bar().encode(
            x=alt.X("requests:Q"), y=alt.Y("path:N", title=None),
            color=alt.Color("path:N", scale=alt.Scale(domain=["cache hit", "cache miss"],
                                                      range=["#2e8b57", "#4169e1"]), legend=None)),
            width="stretch")
        st.write(f"**{len(hits)}** hits · **{len(misses)}** misses · **{len(errors)}** errors")
        source(gw_src + "; cache = hit/miss field written by the cache_lookup step")
    with b:
        st.subheader("End-to-end latency")
        ok_miss = misses[misses["status"] == "ok"]["duration_ms"]
        ok_hit = hits[hits["status"] == "ok"]["duration_ms"]
        lat = pd.DataFrame({"path": ["cache miss (agents)", "cache hit"],
                            "n": [len(ok_miss), len(ok_hit)],
                            "p50": [pct(ok_miss, 50), pct(ok_hit, 50)],
                            "p95": [pct(ok_miss, 95), pct(ok_hit, 95)]})
        st.dataframe(lat, hide_index=True, width="stretch")
        source(gw_src + "; successful requests only; gateway span = ask() start → final answer")

    try:
        n = sum(1 for _ in redis_client().scan_iter(match="s9275:semcache:*"))
        st.metric("Entries in the semantic cache now", n)
        source("live Redis, keys s9275:semcache:* (read at page load)")
    except Exception as exc:  # Redis is optional for the dashboard
        st.caption(f"Live Redis not reachable ({type(exc).__name__}); cache size not shown.")

    st.subheader("Stage latency – 50 confirmed cache misses (Part 4.3)")
    lsum = read_json(str(LATENCY), _mtime(LATENCY))
    if lsum:
        t = pd.DataFrame(lsum["table"]).rename(columns={"pct_of_cache_miss_e2e": "% of miss e2e"})
        st.dataframe(t, hide_index=True, width="stretch")
        st.caption(f"Confirmed misses: {lsum['cache_lookup_misses']}/{lsum['requests_planned']} · "
                   f"{lsum['note']}")
        source(f"`{LATENCY.relative_to(ROOT)}` (latency_experiment.py analyze over spans.jsonl)")

    st.subheader("Recent requests")
    cols = [c for c in ["start", "trace_id", "cache", "outcome", "status", "duration_ms", "question", "error"]
            if c in gw]
    st.dataframe(gw.sort_values("start", ascending=False)[cols].head(25), hide_index=True,
                 width="stretch")
    source(gw_src)


# ------------------------------------------------------------------ 1.2 Evaluation
def evaluation_page() -> None:
    st.title("Evaluation")
    rows, kind = evals(), kinds()
    done = [r for r in rows if r.get("status") == "evaluated"]
    st.header("Part 2 – pipeline evaluation (judge: local qwen3:4b, 1–5)")
    if not done:
        st.warning(f"No evaluated traces in {EVAL}")
    else:
        df = pd.DataFrame([{
            "trace_id": r["trace_id"][:8], "kind": kind.get(r["trace_id"], "other"),
            "question": r["question"], "plan": r["plan_quality"]["score"],
            "writer draft": r["writer_helpfulness"]["score"], "final": r["final_helpfulness"]["score"],
            "final − draft": r["final_vs_draft"]["difference"],
            "final == draft text": r["final_vs_draft"]["final_identical_to_draft"],
            "reviewer": r["review_status"]} for r in done])
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Evaluated traces", len(df))
        c2.metric("Plan quality (mean)", f"{df['plan'].mean():.2f}")
        c3.metric("Writer draft (mean)", f"{df['writer draft'].mean():.2f}")
        c4.metric("Final answer (mean)", f"{df['final'].mean():.2f}")

        by_stage = df.groupby("kind")[["plan", "writer draft", "final"]].mean().reset_index().melt(
            id_vars="kind", var_name="stage", value_name="mean score")
        st.altair_chart(alt.Chart(by_stage).mark_bar().encode(
            x=alt.X("stage:N", sort=["plan", "writer draft", "final"], title=None),
            y=alt.Y("mean score:Q", scale=alt.Scale(domain=[0, 5])),
            color="stage:N", column=alt.Column("kind:N", title="question kind")), width="content")
        st.dataframe(df, hide_index=True, width="stretch")
        source(f"`{EVAL.relative_to(ROOT)}` (evaluator.py), all evaluated traces; "
               "kind from latency_questions.json")

        st.subheader("Final vs draft")
        same = df["final == draft text"].mean()
        st.write(f"Final text identical to the draft in **{same:.0%}** of traces; "
                 f"mean final − draft = **{df['final − draft'].mean():+.2f}**.")

        st.subheader("What the scores say about Planner–Writer–Reviewer coordination")
        appr = df[df["reviewer"] == "approved"]["writer draft"]
        rej = df[df["reviewer"] == "rejected"]["writer draft"]
        rec = df[df["kind"] == "record"]
        rec_rej5 = int(((rec["reviewer"] == "rejected") & (rec["writer draft"] >= 4)).sum())
        st.markdown(f"""
- **Planner → Writer:** plans score low (mean {df['plan'].mean():.2f}) while drafts score higher
  (mean {df['writer draft'].mean():.2f}). The Writer's answer is driven by the database facts the
  gateway attaches, not by the plan; the Planner adds latency (largest stage, Part 4.3) without
  visibly adding quality.
- **Writer → Reviewer:** the Reviewer only approves or rejects; it never rewrites. The final text is the
  draft in {same:.0%} of traces, so the final answer **did not improve** on any trace (difference 0).
  This is a property of the HW8 design, not a judge artefact.
- **Reviewer as a gate:** drafts the Reviewer rejected scored *higher* on average
  ({rej.mean():.2f}, n={len(rej)}) than drafts it approved ({appr.mean():.2f}, n={len(appr)}).
  On record questions – the category where the judge agrees best with the human labels –
  {rec_rej5} rejected drafts scored ≥ 4. The gate is not aligned with answer quality.
- **Caveat:** the judge itself is only weakly aligned with human labels (Part 3 below), especially
  on not-found and off-domain answers, so per-kind scores outside *record* are not reliable.
""")

    st.header("Part 3 – is the judge trustworthy?")
    val = read_json(str(PART3 / "judge_validation.json"), _mtime(PART3 / "judge_validation.json"))
    runs = read_csv(str(PART3 / "judge_runs.csv"), _mtime(PART3 / "judge_runs.csv"))
    if not val:
        st.info("Run validate_judge.py first.")
        return
    v, rep = val["vs_human"]["run1"], val["repeatability"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Spearman ρ (judge vs human)", f"{v['spearman_rho']:.3f}", help=f"p = {v['spearman_p']}")
    c2.metric("Mean absolute difference", f"{v['mean_abs_diff']:.2f}",
              help=f"judge − human on average: {v['mean_judge_minus_human']:+.2f}")
    c3.metric("Cases changed across 3 runs", f"{rep['cases_with_any_change']}/{rep['cases']}")
    c4.metric("Mean / max abs change", f"{rep['mean_abs_change']} / {rep['max_abs_change']}")
    st.caption(f"n = {v['n']} drafts · exact agreement {v['exact_agreement']:.0%} · within 1 point "
               f"{v['within_1']:.0%} · labels frozen in {val['labels_commit'].split()[0]} · "
               f"judge {val['judge']['model']} {val['judge']['options']}")
    if not runs.empty:
        runs["|judge − human|"] = (runs["run1"] - runs["human_label"]).abs()
        agg = runs.groupby("kind")["|judge − human|"].agg(["count", "mean"]).reset_index()
        st.dataframe(agg.rename(columns={"mean": "mean |judge − human|"}), hide_index=True)
        st.dataframe(runs, hide_index=True, width="stretch")
    source("`reports/hw10/part3/judge_validation.json`, `judge_runs.csv` (validate_judge.py); "
           "human labels `reports/hw10/human_labels.csv`")
    st.markdown("""
**Verdict:** the judge is perfectly repeatable (temperature 0, fixed seed) but **not valid enough to gate a
deployment**: it is consistently wrong in the same way. It penalises correct "recall not found" answers as
"did not answer the question", misreads the empty context of off-domain questions, and some of its
reasons describe text the draft does not contain. Before trusting it: fix the rubric for not-found /
off-domain, then re-validate on a new, unseen labelled set with enough cases per kind, a second human
labeller for inter-rater agreement, and a check that its reasons match the draft.
""")


# ------------------------------------------------------------------ 1.3 Trace lookup
def trace_page() -> None:
    st.title("Trace lookup")
    ex = read_json(str(EXAMPLES), _mtime(EXAMPLES)) or {}
    if ex:
        cols = st.columns(len(ex))
        for col, (name, data) in zip(cols, ex.items()):
            if col.button(f"{name} example · {data['trace_id'][:8]}", width="stretch"):
                st.session_state["tid"] = data["trace_id"]
    tid = st.text_input("trace_id (full id or the first characters)", key="tid").strip()
    if not tid:
        st.caption(f"Source: `{SPANS.relative_to(ROOT)}`")
        return
    df = spans_df()
    match = df[df["trace_id"].str.startswith(tid)] if not df.empty else df
    if match.empty:
        st.error("No spans for this trace_id.")
        return
    if match["trace_id"].nunique() > 1:
        st.warning("Several traces start with this prefix – type more characters.")
        st.write(sorted(match["trace_id"].unique()))
        return
    trace_id = match["trace_id"].iloc[0]
    t = match.copy()
    t["order"] = t["stage"].map({s: i for i, s in enumerate(STAGE_ORDER)})
    # Stage order: gateway (the whole request) first, the pipeline stages by start time,
    # evaluation last (it runs after the final answer even if its join timer started earlier).
    t["block"] = t["stage"].map({"gateway": 0, "evaluation": 2}).fillna(1)
    t = t.sort_values(["block", "start", "order"])

    lookup = t[t["stage"] == "cache_lookup"]
    is_hit = not lookup.empty and lookup["cache"].iloc[0] == "hit"
    failed = (t["status"] == "error").any()
    if failed:
        # Root cause = the earliest failing stage on the request path. The gateway (it timed
        # out waiting) and the evaluator (it never got a draft) fail as a consequence.
        errs = t[t["status"] == "error"].sort_values("order")
        root = errs[~errs["stage"].isin(["gateway", "evaluation"])]
        root = root if not root.empty else errs
        st.error(f"FAILED trace · failing stage: **{root['stage'].iloc[0]}** · {root['error'].iloc[0]}  \n"
                 f"Also error as a consequence: "
                 f"{', '.join(s for s in errs['stage'] if s != root['stage'].iloc[0]) or 'none'}")
    elif is_hit:
        st.success("CACHE HIT path · answered from Redis, the agents did not run")
    else:
        st.info("CACHE MISS path · cache_lookup → Kafka: Planner → Writer → Reviewer → evaluator")
    st.code(trace_id)

    t["detail"] = t.get("hop", pd.Series(index=t.index, dtype=str)).fillna("")
    for col in ("cache", "review_status", "outcome"):
        if col in t:
            t["detail"] = t["detail"].where(t["detail"] != "", t[col].fillna(""))
    t["label"] = t["stage"] + t["detail"].map(lambda d: f" ({d})" if d else "")
    show = t[["label", "start_ts", "end_ts", "duration_ms", "status", "error"]].rename(
        columns={"label": "stage", "start_ts": "start", "end_ts": "end"})
    show["status"] = show["status"].map({"ok": "✅ ok", "error": "❌ error"}).fillna(show["status"])
    st.dataframe(show, hide_index=True, width="stretch")

    chart = t[t["stage"] != "gateway"]
    st.altair_chart(alt.Chart(chart).mark_bar().encode(
        x=alt.X("start:T", title="time"), x2="end:T",
        y=alt.Y("label:N", sort=list(chart["label"]), title=None),
        color=alt.Color("status:N", scale=alt.Scale(domain=["ok", "error"], range=["#4169e1", "#d62728"])),
        tooltip=["label", "duration_ms", "status", "error"]), width="stretch")

    ev = next((r for r in evals() if r["trace_id"] == trace_id and r.get("status") == "evaluated"), None)
    if ev:
        st.write(f"Evaluation: plan **{ev['plan_quality']['score']}** · draft "
                 f"**{ev['writer_helpfulness']['score']}** · final **{ev['final_helpfulness']['score']}** "
                 f"· {ev['final_vs_draft']['interpretation']}")
        with st.expander("Question, plan, draft, final"):
            st.json({k: ev[k] for k in ("question", "facts", "plan", "draft", "final_answer",
                                        "review_status", "review_reason")})
    source(f"`{SPANS.relative_to(ROOT)}` (spans), `{EVAL.relative_to(ROOT)}` (scores)")


st.set_page_config(page_title="s9275 ops dashboard", layout="wide")
st.sidebar.markdown("**Xu Wang · DATA 260 HW10**  \nGrocery recall notices · PREFIX s9275")
st.navigation([st.Page(summary_page, title="Summary", url_path="summary", default=True),
               st.Page(evaluation_page, title="Evaluation", url_path="evaluation"),
               st.Page(trace_page, title="Trace lookup", url_path="trace")]).run()
