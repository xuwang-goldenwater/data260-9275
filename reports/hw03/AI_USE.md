# AI_USE — Homework 3

## 1. What I used an AI assistant for, and what I did myself

I did the design and the checking myself. I decided to use a mixed corpus (FDA recall announcements plus 21 CFR Part 7) instead of only openFDA JSON records, because each record is shorter than one chunk and the three chunkers would give almost the same result. I also decided where the corpus is stored, that the raw output is split into two files, that recall is computed from questions.yaml instead of stored, that sentence-window is measured on the single sentence, that annotations go in a separate file, and that HW2 code stays unchanged. I reviewed and approved the five questions and committed them before the retrieval run. I ran all the code on my own computer, labelled annotations.csv by reading the retrieved chunks, took the screenshots, and wrote the first draft of the analysis and conclusion.

I used Claude to explain the assignment and put the steps in order. It found the FDA and eCFR source pages and collected the list of 89 recall announcement URLs. It wrote the code based on my design decisions: the changes to the instructor's auth starter, the fetch, chunking and summary scripts, verify_hw03.py and the Makefile targets. It drafted questions.yaml for me to review, helped debug problems, made the report template, and made the wording of my analysis simpler.

## 2. One AI output that was wrong

The first version of rag_fetch_corpus.py used Python's built-in html.parser. Some FDA pages have broken HTML (a <div> inside a <p>). Because of this, the parser put the whole announcement inside the first paragraph, and the script saved only the title and the summary box. It also skipped tables.

## 3. How the problem was found

After the first download, the corpus was 227,584 bytes. I sorted the files by size, and the smallest ones were only about 500 bytes. When I opened fda_ambriola-company-issues-recall-cheese-products.txt, it had only the title and summary, but the web page has several paragraphs and two tables of expiration dates.

## 4. What was changed and why it works now

The script now uses the lxml parser, which fixes broken HTML the same way a browser does, and reads every paragraph, list item and table row in page order. After running it again, the corpus is 274,233 bytes, the smallest file is 1.4 KB, and the Ambriola file has the full text and both tables. I also checked that the answer to each of the five questions appears in its expected source file.
