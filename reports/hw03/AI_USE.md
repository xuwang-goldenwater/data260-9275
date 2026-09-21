# AI_USE — Homework 3

TODO: write these in your own words. The notes under each question are facts
from the session to start from, not the final answer.

## 1. What I used an AI assistant for, and what I did myself

Notes: Claude explained the assignment; I decided the corpus mix, the storage
location, the raw/ schema (two files), measuring sentence-window on the single
sentence, and a separate annotation file. Claude then wrote the code (auth app
changes, fetch / chunking / summary / verify scripts) and collected the list of
FDA announcement URLs. I ran everything on my machine, took the screenshots,
labelled annotations.csv, and wrote the analysis.

## 2. One AI output that was wrong or unsuitable, or one thing I verified

Notes, candidates:
- The instructor starter's `request.session.clear()` logout does not stop a
  saved cookie from being replayed, because Starlette keeps the session inside
  the signed cookie. Fixed with a server-side session table.
- The first annotation design keyed labels on `chunk_hash` only; two recall
  notices contain the same boilerplate sentence, so labels overwrote each other.

## 3. How I detected the problem or verified the result

TODO

## 4. What I changed and why it works now

TODO
