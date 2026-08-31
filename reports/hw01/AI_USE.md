# AI_USE.md — Homework 1

## 1. What I used an AI assistant for, and what I did myself

I used Claude as a coding assistant for this homework.

**What the assistant did**

- Drafted the HTML, JavaScript, Dockerfile and Python files.
- Explained things I did not know yet: closures, Docker build context, and why
  an ECS Fargate task needs an x86 image.
- Wrote the structure and the first draft of the report and the metrics tables.

**What I did**

- Ran every command and every experiment myself. All screenshots come from my
  own machine and my own runs.
- Made the design decisions after the options were explained to me. I chose the
  four `category` values, and I decided the dropdown should use recall *reason*
  rather than severity class, because severity is assigned by the regulator and
  not by the person filing the notice.

- Wrote`DOMAIN_SCHEMA.md`
- Diagnosed the environment problems: a full disk, an 8 GB memory limit that
  made the first agent run 168 seconds, and an AWS console left in the wrong
  region.
- Read the model output against the source text, which is how I found the
  problem described below.

## 2. An AI output that was wrong

The assistant wrote a grounding check for `agents_demo.py`. It verifies that
every word in a tag also appears in the input text. This is what shows the tags
come from the input rather than from hardcoded domain knowledge.

On my first run it reported two of the three tags as not grounded:

```
tag grounded in the input text?
    yes  peanut butter
    no   milk contamination
    no   product recall
```

## 3. How I detected it

I read the input text again and compared it word by word.

- **`product recall`** — the text contains "product" and "recalling". The tag is
  grounded. **The check was wrong.**
- **`milk contamination`** — the text says "may **contain** undeclared milk".
  The word "contamination" never appears. **The check was right.**

So one result was a false negative and the other was correct. The cause was
that the check compared exact strings. "recall" and "recalling" are the same
word in different forms, but exact matching treats them as different words.

## 4. What I changed, and why it works now

I added a small stemmer that removes one common suffix before comparing.

```python
SUFFIXES = ("ing", "ies", "es", "ed", "s")


def stem(word: str) -> str:
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            base = word[: -len(suffix)]
            if suffix == "ies":
                base += "y"
            return base
    return word
```

Now "recalling" becomes "recall", so the tag matches and the false negative is
gone. "contamination" has no matching suffix, so it is unchanged, and the input
text still does not contain it. That tag is still reported as not grounded.

The fix removes the error without weakening the check. That was the point. A
fix that simply made all three tags pass would have hidden a real finding: the
Reviewer agent had used a word that is not in the source.

The stemmer is deliberately crude and language-general. It contains no domain
vocabulary, so the agent logic stays domain-agnostic.

## Two more model errors I kept in the report

In the Part 4 conversation the model produced two defects that do not exist.

- Turn 1: it said the `count` variable was not declared with `const` or `let`.
  The code declares it on the second line: `let count = 0;`.
- Turn 3: it said `clamp_summary` "uses division". There is no division in that
  function.

Both replies were fluent, correctly formatted, and passed my bullet-only
compliance check. I left them in the report rather than re-running until the
output looked clean. Correct format says nothing about correct content, which
is the reason the check is written in code instead of assumed.
