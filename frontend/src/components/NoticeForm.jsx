import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import api, { toApiError } from "../api/axios.js";

export const CATEGORIES = [
  "Undeclared Allergen",
  "Bacterial Contamination",
  "Foreign Material",
  "Mislabeling",
];

const EMPTY = {
  product_name: "",
  category: "",
  recall_number: "",
  units_affected: 0,
  firm_id: "",
  recall_date: "",
};

// The form shared by the Create and Update pages. It knows nothing about
// Redux: it collects the six fields and hands them to onSubmit. The page
// decides which thunk to dispatch.
//
//   initial      values to start with (Update passes the current record)
//   submitLabel  text on the button
//   onSubmit     async function(notice); throws { status, message } on failure
export default function NoticeForm({ initial = EMPTY, submitLabel, onSubmit }) {
  const [values, setValues] = useState(initial);
  const [firms, setFirms] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Options for the firm dropdown (the related entity). 200 is the largest
  // page the API allows, which covers every seeded firm.
  useEffect(() => {
    api.get("/api/firms", { params: { page: 1, page_size: 200 } })
      .then((res) => {
        const byName = [...res.data.items].sort((a, b) => a.name.localeCompare(b.name));
        setFirms(byName);
      })
      .catch((err) => setError(toApiError(err).message));
  }, []);

  // set("category") returns the onChange handler for that one field.
  const set = (field) => (e) => setValues({ ...values, [field]: e.target.value });

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);

    // Inputs give strings; the API wants numbers for units_affected and firm_id.
    const notice = {
      product_name: values.product_name.trim(),
      category: values.category,
      recall_number: values.recall_number.trim().toUpperCase(),
      units_affected: Number(values.units_affected),
      firm_id: Number(values.firm_id),
    };
    if (values.recall_date) notice.recall_date = values.recall_date;   // blank = today

    try {
      await onSubmit(notice);
    } catch (err) {
      setError(err.message);        // e.g. "recall_number F-0001-2025 already exists"
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="form">
      <label htmlFor="productName">Product name</label>
      <input id="productName" required autoFocus maxLength={255} value={values.product_name}
             placeholder="e.g. Sunrise Valley Creamy Peanut Butter, 16 oz"
             onChange={set("product_name")} />

      <label htmlFor="category">Recall category</label>
      <select id="category" required value={values.category} onChange={set("category")}>
        <option value="" disabled>Choose a category</option>
        {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>

      <label htmlFor="recallNumber">Recall number (unique)</label>
      <input id="recallNumber" required value={values.recall_number}
             placeholder="F-0123-2026" pattern="[Ff]-\d{4}-\d{4}"
             title="Format: F-NNNN-YYYY, for example F-0123-2026"
             onChange={set("recall_number")} />

      <label htmlFor="unitsAffected">Units affected</label>
      <input id="unitsAffected" type="number" min="0" step="1" required
             value={values.units_affected} onChange={set("units_affected")} />

      <label htmlFor="firm">Recalling firm</label>
      <select id="firm" required value={values.firm_id} onChange={set("firm_id")}>
        <option value="" disabled>{firms.length ? "Choose a firm" : "Loading firms…"}</option>
        {firms.map((f) => <option key={f.id} value={f.id}>{f.name} ({f.state})</option>)}
      </select>

      <label htmlFor="recallDate">Recall date</label>
      <input id="recallDate" type="date" value={values.recall_date} onChange={set("recall_date")} />

      {error && <div className="alert">{error}</div>}
      <div className="form-actions">
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? "Saving…" : submitLabel}
        </button>
        <Link className="btn" to="/">Cancel</Link>
      </div>
    </form>
  );
}
