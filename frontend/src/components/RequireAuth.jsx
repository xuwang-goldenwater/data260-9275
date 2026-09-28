import React from "react";
import { Link } from "react-router-dom";

// Wraps the Create / Update / Delete routes. The backend rejects these calls
// without a session anyway; this just shows the reason instead of a broken form.
export default function RequireAuth({ user, children }) {
  if (!user) {
    return (
      <div className="card">
        <h2>Login required</h2>
        <p className="notice">
          You need to log in to manage recall notices. <Link to="/login">Log in</Link>
        </p>
      </div>
    );
  }
  return children;
}
