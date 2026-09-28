import React from "react";
import { Link, useNavigate } from "react-router-dom";

// Route "/". Shows the recall notices one page at a time (5,000 seeded rows
// are too many to render at once). Update/Delete pass the chosen record to
// the next page through router state, so those routes are plain /update and /delete.
export default function Home({ user, notices, loading, page, pageSize, onPageChange }) {
  const navigate = useNavigate();

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

      {loading ? (
        <p className="notice">Loading…</p>
      ) : notices.length === 0 ? (
        <p className="notice">No recall notices on this page.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Product</th>
                <th>Category</th>
                <th>Recalling firm</th>
                <th>Recall date</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {notices.map((n) => (
                <tr key={n.id}>
                  <td>{n.id}</td>
                  <td>{n.product_name}</td>
                  <td>{n.category}</td>
                  <td>{n.firm ? `${n.firm.name} (${n.firm.state})` : "—"}</td>
                  <td>{n.recall_date}</td>
                  <td className="actions">
                    <button className="btn" onClick={() => navigate("/update", { state: { id: n.id } })}>
                      Update
                    </button>
                    <button className="btn danger" onClick={() => navigate("/delete", { state: { id: n.id } })}>
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
        <button className="btn" disabled={page === 1 || loading} onClick={() => onPageChange(page - 1)}>
          ← Previous
        </button>
        <span>Page {page}</span>
        <button className="btn" disabled={notices.length < pageSize || loading}
                onClick={() => onPageChange(page + 1)}>
          Next →
        </button>
      </div>
    </div>
  );
}
