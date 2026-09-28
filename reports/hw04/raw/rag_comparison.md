# No-RAG vs Basic RAG vs Context-engineered RAG (k = 3)

## Q1 (answer in one chunk)

**Q:** What toxin caused the recall of a2 Platinum infant formula, and what produces that toxin?

**Expected:** Cereulide, a heat-stable toxin produced by some strains of the bacterium Bacillus cereus.

| Config | Chunks in prompt (score) | Retrieval ok | Refused | Answer |
|---|---|---|---|---|
| A | — | None | False | The toxin caused by the recall of a2 Platinum infant formula was **saxitoxin**, which is produced by certain species of **marine algae** (such as *Alexandrium* spp.). Saxitoxin is a potent neurotoxin associated with harm… |
| B | fda_a2-platinum-usa-label-infant-formula#0 (0.74), fda_nara-organics-recalls-all-lots-nara#0 (0.54), fda_a2-platinum-usa-label-infant-formula#1 (0.54) | True | False | The toxin that caused the recall of the a2 Platinum infant formula is cereulide, which is produced by some strains of the bacterium Bacillus cereus. |
| C | fda_a2-platinum-usa-label-infant-formula#0 (0.74), fda_nara-organics-recalls-all-lots-nara#0 (0.54), fda_a2-platinum-usa-label-infant-formula#1 (0.54) | True | False | The toxin that caused the recall of a2 Platinum infant formula is cereulide, which is produced by some strains of the bacterium Bacillus cereus [S1]. |

## Q2 (answer needs two chunks)

**Q:** Under 21 CFR Part 7, what is a Class I recall, and how often does a recalling firm generally submit recall status reports?

**Expected:** Class I: a reasonable probability that use of or exposure to the product will cause serious adverse health consequences or death (7.3(m)(1)). Status reports: at an interval FDA specifies for each recall, generally every 2 to 4 weeks (7.53(a)).

| Config | Chunks in prompt (score) | Retrieval ok | Refused | Answer |
|---|---|---|---|---|
| A | — | None | False | Under 21 CFR Part 7, a **Class I recall** is a recall of a product that could cause **serious adverse health consequences or death**. A recalling firm generally submits **recall status reports** **every 7 calendar days**… |
| B | ecfr_21cfr_part7#11 (0.64), ecfr_21cfr_part7#9 (0.58), ecfr_21cfr_part7#7 (0.57) | False | False | Under 21 CFR Part 7, a Class I recall is the most serious type of recall, involving products that pose a high risk of serious adverse health consequences or death. A recalling firm generally submits recall status reports… |
| C | ecfr_21cfr_part7#11 (0.64), ecfr_21cfr_part7#9 (0.58), ecfr_21cfr_part7#7 (0.57) | False | False | A Class I recall is a recall that involves products that can cause serious adverse health consequences or death. The recalling firm generally submits recall status reports every 2 to 4 weeks [S1]. |

## Q3 (similar information across documents)

**Q:** According to the recall announcements, what health risks does Listeria monocytogenes pose?

**Expected:** Serious and sometimes fatal infections in young children, frail or elderly people and others with weakened immune systems; short-term symptoms such as high fever, severe headache, stiffness, nausea, abdominal pain and diarrhea in healthy people; miscarriages and stillbirths in pregnant women. (The same paragraph appears, with small wording changes, in several different recall notices.)

| Config | Chunks in prompt (score) | Retrieval ok | Refused | Answer |
|---|---|---|---|---|
| A | — | None | False | Listeria monocytogenes can cause severe illness, including listeriosis, which can lead to symptoms such as fever, muscle aches, nausea, and diarrhea. It is particularly dangerous for pregnant women, newborns, the elderly… |
| B | fda_slade-gorton-co-inc-recalls-one#0 (0.67), fda_ambriola-company-issues-recall-cheese-products#0 (0.64), fda_kettle-cuisine-recalls-marketside-tomato-bisque#1 (0.62) | True | False | Listeria monocytogenes can cause serious and sometimes fatal infections in young children, frail or elderly people, and those with weakened immune systems. It can also lead to miscarriages and stillbirths in pregnant wom… |
| C | fda_slade-gorton-co-inc-recalls-one#0 (0.67), fda_ambriola-company-issues-recall-cheese-products#0 (0.64), fda_kettle-cuisine-recalls-marketside-tomato-bisque#1 (0.62) | True | False | Listeria monocytogenes can cause serious and sometimes fatal infections in young children, frail or elderly people, and others with weakened immune systems. It can also lead to miscarriages and stillbirths among pregnant… |

## Q4 (ambiguous)

**Q:** What should I do if I bought the recalled product?

**Expected:** Ambiguous - the collection has dozens of recalls and the question does not say which product. A good answer says it depends on the product (or asks which one) and may give the common instruction found in the notices: do not consume it; return it to the place of purchase for a refund or discard it.

| Config | Chunks in prompt (score) | Retrieval ok | Refused | Answer |
|---|---|---|---|---|
| A | — | None | False | If you bought a recalled product, stop using it immediately. Contact the manufacturer or retailer for instructions, which may include returning the product, getting a replacement, or a refund. Check the recall notice for… |
| B | fda_fresh-ready-foods-llc-recalls-spicy#1 (0.65), fda_pt-organics-limited-recalls-select-pumpkin#1 (0.62), fda_if-copack-llc-dba-initiative-foods#1 (0.62) | True | False | If you bought the recalled product, you should immediately stop using it, discard it, or return it to the place of purchase for a refund. Do not consume or feed it to anyone. Contact the company or the FDA for more infor… |
| C | fda_fresh-ready-foods-llc-recalls-spicy#1 (0.65), fda_pt-organics-limited-recalls-select-pumpkin#1 (0.62), fda_if-copack-llc-dba-initiative-foods#1 (0.62) | True | False | If you bought the recalled product, you should discontinue use and dispose of it immediately or return it to the place of purchase for a refund [S1][S2][S3]. If you have any concerns about your health after consumption, … |

## Q5 (answer not in the documents)

**Q:** How much was Prairie Farms fined by the FDA for its fat free milk recall?

**Expected:** Must refuse. The Prairie Farms notice exists, but no document mentions a fine or penalty.

| Config | Chunks in prompt (score) | Retrieval ok | Refused | Answer |
|---|---|---|---|---|
| A | — | None | False | Prairie Farms was fined $1.2 million by the FDA for its fat-free milk recall in 2013. |
| B | fda_prairie-farms-announces-recall-prairie-farms#0 (0.78), fda_clover-hill-dairy-recalls-soft-ricottarequeson#1 (0.61), fda_frito-lay-issues-voluntary-allergy-alert#1 (0.58) | None | True | The context provided does not mention any fine imposed by the FDA on Prairie Farms for the fat free milk recall. Therefore, it is not specified how much, if any, Prairie Farms was fined. |
| C | fda_prairie-farms-announces-recall-prairie-farms#0 (0.78), fda_clover-hill-dairy-recalls-soft-ricottarequeson#1 (0.61), fda_frito-lay-issues-voluntary-allergy-alert#1 (0.58) | None | True | I cannot answer this question from the provided documents. |

## Q6 (unrelated)

**Q:** Who won the 2022 FIFA World Cup?

**Expected:** Must refuse: nothing in the corpus is about football.

| Config | Chunks in prompt (score) | Retrieval ok | Refused | Answer |
|---|---|---|---|---|
| A | — | None | False | Argentina won the 2022 FIFA World Cup. |
| B | fda_mondelez-global-llc-expands-voluntary-recall#1 (0.13), fda_gerber-products-company-announces-voluntary-recall#1 (0.13), fda_frito-lay-issues-voluntary-allergy-alert#1 (0.11) | None | False | France won the 2022 FIFA World Cup. |
| C | — | None | True | I cannot answer this question from the provided documents. |
