import React, { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { getNotice } from "../api/client.js";

// Route "/delete". Shows which notice will be removed, then calls onDelete.
export default function DeleteRecord({ onDelete }) {
  const id = useLocation().state?.id;
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!id) return;
    getNotice(id).then(setNotice).catch((err) => setError(err.message));
  }, [id]);

  if (!id) {
    return (
      <div className="card narrow">
        <h2>Delete recall notice</h2>
        <p className="notice">Choose a notice from the <Link to="/">list</Link> and click Delete.</p>
      </div>
    );
  }

  async function handleDelete() {
    setError("");
    setBusy(true);
    try {
      await onDelete(id);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <div className="card narrow">
      <h2>Delete recall notice #{id}</h2>
      {notice ? (
        <p>
          <b>{notice.product_name}</b> — {notice.category}
          {notice.firm ? `, ${notice.firm.name}` : ""}
        </p>
      ) : (
        !error && <p className="notice">Loading…</p>
      )}
      {error && <div className="alert">{error}</div>}
      <div className="form-actions">
        <button className="btn danger" onClick={handleDelete} disabled={busy || !notice}>
          {busy ? "Deleting…" : "Delete Recall Notice"}
        </button>
        <Link className="btn" to="/">Cancel</Link>
      </div>
    </div>
  );
}
