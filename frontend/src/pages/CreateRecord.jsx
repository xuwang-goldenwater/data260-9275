import React from "react";
import { useDispatch } from "react-redux";
import { useNavigate } from "react-router-dom";

import NoticeForm from "../components/NoticeForm.jsx";
import { createNotice } from "../features/notices/noticesSlice.js";

// Route "/create". Dispatches the createNotice thunk; on success the slice has
// already put the new notice at the top of the list, so Home shows it at once.
export default function CreateRecord() {
  const dispatch = useDispatch();
  const navigate = useNavigate();

  async function handleCreate(notice) {
    // unwrap(): give back the new notice on success, throw { status, message }
    // on failure. NoticeForm catches the error and shows it under the fields.
    await dispatch(createNotice(notice)).unwrap();
    navigate("/");
  }

  return (
    <div className="card narrow">
      <h2>File a new recall notice</h2>
      <NoticeForm submitLabel="File Recall Notice" onSubmit={handleCreate} />
    </div>
  );
}
