import React from "react";
import { Link, NavLink } from "react-router-dom";

// "Add Record" is only shown to a logged-in user.
export default function Navbar({ user, onLogout }) {
  return (
    <nav className="navbar">
      <Link to="/" className="brand">Recall Notice Desk</Link>
      <div className="nav-links">
        <NavLink to="/" end>Notices</NavLink>
        {user && <NavLink to="/create">Add Record</NavLink>}
      </div>
      <div className="nav-user">
        {user ? (
          <>
            <span>{user.email}</span>
            <button className="btn" onClick={onLogout}>Log out</button>
          </>
        ) : (
          <Link className="btn primary" to="/login">Log in</Link>
        )}
      </div>
    </nav>
  );
}
