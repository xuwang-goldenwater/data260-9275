# RAG evaluation (k = 3)

Accuracy = correct answers / 6 (for Q5/Q6 the correct answer is a refusal).  
Faithfulness = grounded / answers that were not refusals (B and C only).  
Format compliance = C answers that are the exact refusal sentence or cite valid [S#] sources.  
Robustness = Q5/Q6 refused, and Q1-Q4 not wrongly refused.

| Config | Correct retrieval (Q1-Q4) | Accuracy | Faithfulness | Format compliance | Robustness: refused Q5/Q6 | Robustness: over-refusals Q1-Q4 |
|---|---|---|---|---|---|---|
| A | n/a | 1/6 | n/a | n/a | 0/2 | 0/4 |
| B | 3/4 | 5/6 | 1/5 | n/a | 1/2 | 0/4 |
| C | 3/4 | 6/6 | 2/4 | 6/6 | 2/2 | 0/4 |

| Q | Config | Retrieval | Correct | Grounded | Refused | Format |
|---|---|---|---|---|---|---|
| Q1 | A |  | False | n/a | False |  |
| Q2 | A |  | False | n/a | False |  |
| Q3 | A |  | False | n/a | False |  |
| Q4 | A |  | True | n/a | False |  |
| Q5 | A |  | False | n/a | False |  |
| Q6 | A |  | False | n/a | False |  |
| Q1 | B | True | True | yes | False |  |
| Q2 | B | False | True | no | False |  |
| Q3 | B | True | True | no | False |  |
| Q4 | B | True | True | no | False |  |
| Q5 | B |  | True | n/a (refused) | True |  |
| Q6 | B |  | False | no | False |  |
| Q1 | C | True | True | yes | False | True |
| Q2 | C | False | True | no | False | True |
| Q3 | C | True | True | yes | False | True |
| Q4 | C | True | True | no | False | True |
| Q5 | C |  | True | n/a (refused) | True | True |
| Q6 | C |  | True | n/a (refused) | True | True |
