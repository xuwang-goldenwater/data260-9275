import React, { useEffect } from "react";
import { useDispatch, useSelector } from "react-redux";
import { Link, useNavigate } from "react-router-dom";

import { deleteNotice, fetchNotices } from "../features/notices/noticesSlice.js";

// Route "/". The list is not passed in as a prop any more: this page reads it
// from the Redux store, so it redraws by itself whenever a notice is created,
// updated or deleted anywhere in the app.
export default function Home({ user }) {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const { items, page, hasMore, status, error } = useSelector((state) => state.notices);
  const loading = status === "loading";

  // Nothing loaded yet (first visit, or just logged in): ask for page 1.
  useEffect(() => {
    if (user && status === "idle") dispatch(fetchNotices(1));
  }, [user, status, dispatch]);

  function handleDelete(notice) {
    const label = `${notice.recall_number} - ${notice.product_name}`;
    if (window.confirm(`Delete recall notice ${label}?`)) {
      dispatch(deleteNotice(notice.id));     // on success the slice removes the row
    }
  }

  if (!user) {
    return (
      <div className="card">
        <h2>Recall notices</h2>
        <p className="notice">Login required. <Link to="/login">Log in</Link> to view and manage recall notices.</p>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="card-header">
        <h2>Recall notices</h2>
        <Link className="btn primary" to="/create">+ Add Record</Link>
      </div>

      {error && <div className="alert">{error.message}</div>}

      {loading ? (
        <p className="notice">Loading…</p>
      ) : items.length === 0 ? (
        <p className="notice">No recall notices on this page.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Recall no.</th>
                <th>Product</th>
                <th>Category</th>
                <th>Units</th>
                <th>Recalling firm</th>
                <th className="nowrap">Recall date</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((n) => (
                <tr key={n.id}>
                  <td>{n.id}</td>
                  <td className="nowrap">{n.recall_number}</td>
                  <td>{n.product_name}</td>
                  <td>{n.category}</td>
                  <td>{n.units_affected.toLocaleString()}</td>
                  <td>{n.firm.name} ({n.firm.state})</td>
                  <td className="nowrap">{n.recall_date}</td>
                  <td className="actions">
                    <button className="btn" onClick={() => navigate("/update", { state: { id: n.id } })}>
                      Update
                    </button>
                    <button className="btn danger" onClick={() => handleDelete(n)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="pager">
        <button className="btn" disabled={page === 1 || loading}
                onClick={() => dispatch(fetchNotices(page - 1))}>
          ← Previous
        </button>
        <span>Page {page}</span>
        <button className="btn" disabled={!hasMore || loading}
                onClick={() => dispatch(fetchNotices(page + 1))}>
          Next →
        </button>
      </div>
    </div>
  );
}
