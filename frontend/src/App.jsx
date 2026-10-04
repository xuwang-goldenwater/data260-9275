import React, { useEffect, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";

import api, { toApiError } from "./api/axios.js";
import Navbar from "./components/Navbar.jsx";
import RequireAuth from "./components/RequireAuth.jsx";
import { resetNotices } from "./features/notices/noticesSlice.js";
import Login from "./pages/Login.jsx";
import Home from "./pages/Home.jsx";
import CreateRecord from "./pages/CreateRecord.jsx";
import UpdateRecord from "./pages/UpdateRecord.jsx";

// HW5: App only looks after login state and routing. The notice list, and the
// create / update / delete calls, moved to the Redux slice
// (features/notices/noticesSlice.js); each page talks to the store directly.
export default function App() {
  const navigate = useNavigate();
  const dispatch = useDispatch();

  // user === undefined: still asking the server; null: logged out; object: logged in
  const [user, setUser] = useState(undefined);
  const noticesError = useSelector((state) => state.notices.error);

  // On first load, ask the backend whether the browser already has a live session.
  useEffect(() => {
    api.get("/api/auth/me").then((res) => setUser(res.data)).catch(() => setUser(null));
  }, []);

  // A 401 on the list means the server-side session is gone: show the logged-out UI.
  useEffect(() => {
    if (noticesError?.status === 401) setUser(null);
  }, [noticesError]);

  // Logged out (Log out button, or expired session): empty the store, so the
  // next login starts from status "idle" and Home loads page 1 again.
  useEffect(() => {
    if (user === null) dispatch(resetNotices());
  }, [user, dispatch]);

  async function onLogin(email, password) {
    try {
      const res = await api.post("/api/auth/login", { email, password });   // server sets the cookie
      setUser(res.data);
      navigate("/");
    } catch (err) {
      throw toApiError(err);           // Login.jsx shows err.message
    }
  }

  async function onLogout() {
    await api.post("/api/auth/logout").catch(() => {});
    setUser(null);
    navigate("/");
  }

  if (user === undefined) {
    return <div className="container"><p className="notice">Checking session…</p></div>;
  }

  return (
    <div className="container">
      <Navbar user={user} onLogout={onLogout} />

      <Routes>
        <Route path="/" element={<Home user={user} />} />
        <Route
          path="/login"
          element={user ? <Navigate to="/" replace /> : <Login onLogin={onLogin} />}
        />
        <Route
          path="/create"
          element={<RequireAuth user={user}><CreateRecord /></RequireAuth>}
        />
        <Route
          path="/update"
          element={<RequireAuth user={user}><UpdateRecord /></RequireAuth>}
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}
