import React, { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { CATEGORIES, getNotice } from "../api/client.js";

// Route "/update". The record id arrives through router state from Home;
// the current values are then loaded from the backend so the form is never stale.
export default function UpdateRecord({ onUpdate }) {
  const id = useLocation().state?.id;
  const [productName, setProductName] = useState("");
  const [category, setCategory] = useState("");
  const [loading, setLoading] = useState(Boolean(id));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!id) return;
    getNotice(id)
      .then((n) => {
        setProductName(n.product_name);
        setCategory(n.category);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  if (!id) {
    return (
      <div className="card narrow">
        <h2>Update recall notice</h2>
        <p className="notice">Choose a notice from the <Link to="/">list</Link> and click Update.</p>
      </div>
    );
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await onUpdate(id, { product_name: productName.trim(), category });
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="card narrow">
      <h2>Update recall notice #{id}</h2>
      {loading ? (
        <p className="notice">Loading…</p>
      ) : (
        <form onSubmit={handleSubmit} className="form">
          <label htmlFor="productName">Product name</label>
          <input id="productName" required value={productName}
                 onChange={(e) => setProductName(e.target.value)} />

          <label htmlFor="category">Recall category</label>
          <select id="category" required value={category} onChange={(e) => setCategory(e.target.value)}>
            {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>

          {error && <div className="alert">{error}</div>}
          <div className="form-actions">
            <button className="btn primary" type="submit" disabled={busy}>
              {busy ? "Saving…" : "Save Recall Notice"}
            </button>
            <Link className="btn" to="/">Cancel</Link>
          </div>
        </form>
      )}
    </div>
  );
}
