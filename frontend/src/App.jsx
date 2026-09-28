import React, { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";

import Navbar from "./components/Navbar.jsx";
import RequireAuth from "./components/RequireAuth.jsx";
import Login from "./pages/Login.jsx";
import Home from "./pages/Home.jsx";
import CreateRecord from "./pages/CreateRecord.jsx";
import UpdateRecord from "./pages/UpdateRecord.jsx";
import DeleteRecord from "./pages/DeleteRecord.jsx";
import * as api from "./api/client.js";

const PAGE_SIZE = 50;

export default function App() {
  const navigate = useNavigate();

  // user === undefined: still asking the server; null: logged out; object: logged in
  const [user, setUser] = useState(undefined);
  const [notices, setNotices] = useState([]);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // On first load, ask the backend whether the browser already has a live session.
  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null));
  }, []);

  // Any 401 means the server-side session is gone: show the logged-out UI.
  const handleError = useCallback((err) => {
    if (err.status === 401) {
      setUser(null);
      setNotices([]);
    }
    setError(err.message);
  }, []);

  const loadNotices = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.listNotices(page, PAGE_SIZE);
      setNotices(data.items);
    } catch (err) {
      handleError(err);
    } finally {
      setLoading(false);
    }
  }, [page, handleError]);

  // Fetch the list whenever the user logs in or changes page.
  useEffect(() => {
    if (user) loadNotices();
    else setNotices([]);
  }, [user, loadNotices]);

  // ---- handlers passed down as props ----

  async function onLogin(email, password) {
    const loggedIn = await api.login(email, password);   // server sets the cookie
    setUser(loggedIn);
    setPage(1);
    navigate("/");
  }

  async function onLogout() {
    await api.logout().catch(() => {});
    setUser(null);
    navigate("/");
  }

  async function onAdd(notice) {
    await api.createNotice(notice);          // MySQL assigns the AUTO_INCREMENT id
    if (page === 1) await loadNotices();     // new notices are dated today -> top of page 1
    else setPage(1);
    navigate("/");
  }

  async function onUpdate(id, notice) {
    const updated = await api.updateNotice(id, notice);
    setNotices((prev) => prev.map((n) => (n.id === id ? updated : n)));
    navigate("/");
  }

  async function onDelete(id) {
    await api.deleteNotice(id);
    await loadNotices();                     // refill the page from the database
    navigate("/");
  }

  if (user === undefined) {
    return <div className="container"><p className="notice">Checking session…</p></div>;
  }

  return (
    <div className="container">
      <Navbar user={user} onLogout={onLogout} />
      {error && <div className="alert">{error}</div>}

      <Routes>
        <Route
          path="/"
          element={
            <Home
              user={user}
              notices={notices}
              loading={loading}
              page={page}
              pageSize={PAGE_SIZE}
              onPageChange={setPage}
            />
          }
        />
        <Route
          path="/login"
          element={user ? <Navigate to="/" replace /> : <Login onLogin={onLogin} />}
        />
        <Route
          path="/create"
          element={<RequireAuth user={user}><CreateRecord onAdd={onAdd} /></RequireAuth>}
        />
        <Route
          path="/update"
          element={<RequireAuth user={user}><UpdateRecord onUpdate={onUpdate} /></RequireAuth>}
        />
        <Route
          path="/delete"
          element={<RequireAuth user={user}><DeleteRecord onDelete={onDelete} /></RequireAuth>}
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}
