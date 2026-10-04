import React, { useEffect, useState } from "react";
import { useDispatch } from "react-redux";
import { useLocation, useNavigate } from "react-router-dom";

import api, { toApiError } from "../api/axios.js";
import NoticeForm from "../components/NoticeForm.jsx";
import { updateNotice } from "../features/notices/noticesSlice.js";

// Route "/update". The record is selected by ID: either the ID arrives from
// the Update button on Home (router state), or it is typed into the box here.
// The current values are read from the backend, edited in NoticeForm, and
// saved by dispatching the updateNotice thunk.
export default function UpdateRecord() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const idFromList = useLocation().state?.id;

  const [idInput, setIdInput] = useState(idFromList ? String(idFromList) : "");
  const [notice, setNotice] = useState(null);       // the record being edited
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load(id) {
    setError("");
    setNotice(null);
    setLoading(true);
    try {
      const res = await api.get(`/api/notices/${id}`);
      setNotice(res.data);
    } catch (err) {
      setError(toApiError(err).message);            // e.g. "Recall notice 999999 not found"
    } finally {
      setLoading(false);
    }
  }

  // Came from the list: load that record straight away.
  useEffect(() => {
    if (idFromList) load(idFromList);
  }, [idFromList]);

  async function handleUpdate(values) {
    // On success the slice swaps the old copy in the list for the new one.
    await dispatch(updateNotice({ id: notice.id, notice: values })).unwrap();
    navigate("/");
  }

  return (
    <div className="card narrow">
      <h2>Update recall notice</h2>

      <form className="id-picker" onSubmit={(e) => { e.preventDefault(); load(Number(idInput)); }}>
        <label htmlFor="noticeId">Notice ID</label>
        <input id="noticeId" type="number" min="1" required value={idInput}
               onChange={(e) => setIdInput(e.target.value)} />
        <button className="btn" type="submit" disabled={loading}>Load</button>
      </form>

      {loading && <p className="notice">Loading…</p>}
      {error && <div className="alert">{error}</div>}

      {notice && (
        <NoticeForm
          key={notice.id}                           // a different record starts a fresh form
          initial={{
            product_name: notice.product_name,
            category: notice.category,
            recall_number: notice.recall_number,
            units_affected: notice.units_affected,
            firm_id: String(notice.firm_id),
            recall_date: notice.recall_date,
          }}
          submitLabel="Save Recall Notice"
          onSubmit={handleUpdate}
        />
      )}
    </div>
  );
}
