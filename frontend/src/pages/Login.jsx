import React, { useState } from "react";

// Email + password. On success the backend answers with Set-Cookie
// (HttpOnly, opaque token); this component never touches the cookie.
export default function Login({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await onLogin(email.trim(), password);
    } catch (err) {
      setError(err.status === 401 ? "Invalid email or password." : err.message);
      setBusy(false);
    }
  }

  return (
    <div className="card narrow">
      <h2>Log in</h2>
      <form onSubmit={handleSubmit} className="form">
        <label htmlFor="email">Email</label>
        <input id="email" type="email" required autoFocus value={email}
               onChange={(e) => setEmail(e.target.value)} />

        <label htmlFor="password">Password</label>
        <input id="password" type="password" required value={password}
               onChange={(e) => setPassword(e.target.value)} />

        {error && <div className="alert">{error}</div>}
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? "Logging in…" : "Log in"}
        </button>
      </form>
    </div>
  );
}
