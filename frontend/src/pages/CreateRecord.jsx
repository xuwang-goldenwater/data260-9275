import React, { useState } from "react";
import { Link } from "react-router-dom";

import { CATEGORIES } from "../api/client.js";

// Route "/create". onAdd (from App) POSTs to the backend and redirects home.
export default function CreateRecord({ onAdd }) {
  const [productName, setProductName] = useState("");   // primary field
  const [category, setCategory] = useState("");         // secondary field
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await onAdd({ product_name: productName.trim(), category });
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="card narrow">
      <h2>File a new recall notice</h2>
      <form onSubmit={handleSubmit} className="form">
        <label htmlFor="productName">Product name</label>
        <input id="productName" required autoFocus value={productName}
               placeholder="e.g. Sunrise Valley Creamy Peanut Butter, 16 oz"
               onChange={(e) => setProductName(e.target.value)} />

        <label htmlFor="category">Recall category</label>
        <select id="category" required value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="" disabled>Choose a category</option>
          {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>

        {error && <div className="alert">{error}</div>}
        <div className="form-actions">
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? "Filing…" : "File Recall Notice"}
          </button>
          <Link className="btn" to="/">Cancel</Link>
        </div>
      </form>
    </div>
  );
}
