# DOMAIN_SCHEMA.md

**DOMAIN_ID:** 3 — Grocery supply and recall notices
**Entity:** `RecallNotice`

A recall notice is a public announcement that a food product already on the
market is being pulled back because of a safety or labeling problem. Most
recalls are started voluntarily by the company. This application is the form
used to file a new recall notice into the system.

These field names are used in three places and must stay identical: the `id`
attributes in the HTML form, the keys used in the JavaScript, and the JSON sent
to the agent in Part 2.

## Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `productName` | string | yes | Name of the recalled product, with size or packaging if relevant. Used as the `title` for the Part 2 agent. |
| `recallingFirm` | string | yes | Company issuing the recall. |
| `submitterEmail` | string (email) | yes | Email of the person filing the notice. |
| `description` | string | yes | What is wrong, which lots and dates are affected, and what consumers should do. Used as the `content` for the Part 2 agent. |
| `category` | enum | yes | Reason for the recall. See below. |
| `agreedToTerms` | boolean | yes | Must be true. |
| `submissionDate` | string (ISO 8601) | derived | Added in JavaScript at submission time. Not a form input. |

## `category` values

```
Undeclared Allergen
Bacterial Contamination
Foreign Material
Mislabeling
```

These are the three most common real causes of FDA food recalls plus labeling
error. In Q1 2026, undeclared allergens accounted for 40.7% of FDA food
recalls, foreign material 17.1%, and bacterial contamination 15.7%.

Real recall notices also carry a severity class (Class I, II, or III), but that
is assigned by the regulator after review, not by the person submitting the
notice. It is not part of this form.

## Validation rules

| Rule | Enforced by |
|---|---|
| `productName` not empty | HTML `required` |
| `recallingFirm` not empty | HTML `required` |
| `submitterEmail` not empty and valid email format | HTML `type="email"` + `required` |
| `description` not empty | HTML `required` |
| `description` longer than 25 characters | JavaScript, shows an alert if it fails |
| `category` is one of the four values above | HTML `<select>`, placeholder option disabled |
| `agreedToTerms` is true | JavaScript, shows an alert if it fails |

`productName` gets focus automatically when the page loads.

## Example record

```json
{
  "productName": "Sunrise Valley Creamy Peanut Butter, 16 oz jar",
  "recallingFirm": "Sunrise Valley Foods, Inc.",
  "submitterEmail": "quality@sunrisevalleyfoods.com",
  "category": "Undeclared Allergen",
  "description": "Sunrise Valley Foods is voluntarily recalling 16 oz jars of Creamy Peanut Butter with lot codes SV2451 through SV2458 and best-by dates from 2027-03-11 to 2027-03-18. Routine internal testing found the affected lots may contain undeclared milk from a shared production line. People with an allergy or severe sensitivity to milk risk a serious or life-threatening allergic reaction. The product was distributed to retail stores in California, Nevada, and Oregon. Consumers should not eat the product and may return it to the place of purchase for a full refund.",
  "agreedToTerms": true,
  "submissionDate": "2026-08-29T14:32:07.512Z"
}
```

## How these fields are used

- **Part 1:** the seven form controls map to the seven fields above.
- **Part 2:** the agent receives `{ "title": productName, "content": description }`
  and derives the tags and summary from that text only.
- **Part 3:** one record in this shape is frozen at
  `reports/hw01/cases/nondeterminism_input.json` and reused for all 40 runs.
