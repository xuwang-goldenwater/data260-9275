// Redux state for recall notices (the primary entity).
//
//   thunks   - go to the FastAPI backend with Axios, then report success or failure
//   reducers - change the list held in the store when a thunk succeeds
//
// A page never calls the backend itself. It dispatches a thunk, and reads the
// result back from the store.
import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";

import api, { toApiError } from "../../api/axios.js";

export const PAGE_SIZE = 50;

// ---- async thunks (one per backend call) -----------------------------------
// Each thunk produces three actions automatically: pending, fulfilled, rejected.
// `return` becomes the payload of fulfilled; rejectWithValue becomes the
// payload of rejected.

// GET /api/notices?page=&page_size=
export const fetchNotices = createAsyncThunk(
  "notices/fetch",
  async (page = 1, { rejectWithValue }) => {
    try {
      const res = await api.get("/api/notices", { params: { page, page_size: PAGE_SIZE } });
      return res.data;                        // { page, page_size, items: [...] }
    } catch (err) {
      return rejectWithValue(toApiError(err));
    }
  }
);

// POST /api/notices
export const createNotice = createAsyncThunk(
  "notices/create",
  async (notice, { rejectWithValue }) => {
    try {
      const res = await api.post("/api/notices", notice);
      return res.data;                        // the new notice, with its id
    } catch (err) {
      return rejectWithValue(toApiError(err));
    }
  }
);

// PUT /api/notices/{id}
export const updateNotice = createAsyncThunk(
  "notices/update",
  async ({ id, notice }, { rejectWithValue }) => {
    try {
      const res = await api.put(`/api/notices/${id}`, notice);
      return res.data;                        // the notice after the change
    } catch (err) {
      return rejectWithValue(toApiError(err));
    }
  }
);

// DELETE /api/notices/{id}
export const deleteNotice = createAsyncThunk(
  "notices/delete",
  async (id, { rejectWithValue }) => {
    try {
      await api.delete(`/api/notices/${id}`);
      return id;                              // 204 has no body, so hand back the id
    } catch (err) {
      return rejectWithValue(toApiError(err));
    }
  }
);

// ---- the slice ---------------------------------------------------------------

const initialState = {
  items: [],          // the notices on the page being shown
  page: 1,
  hasMore: false,     // true when the page came back full, so a next page may exist
  status: "idle",     // idle -> loading -> succeeded | failed
  error: null,        // { status, message } from the last failed fetch or delete
};

const noticesSlice = createSlice({
  name: "notices",
  initialState,
  reducers: {
    // Logout: forget everything, so the next login loads a fresh list.
    resetNotices: () => initialState,
  },
  // What each thunk result does to the state. Redux Toolkit lets the code
  // "modify" state directly; underneath it builds a new state object.
  extraReducers: (builder) => {
    builder
      // fetching
      .addCase(fetchNotices.pending, (state) => {
        state.status = "loading";
        state.error = null;
      })
      .addCase(fetchNotices.fulfilled, (state, action) => {
        state.status = "succeeded";
        state.items = action.payload.items;
        state.page = action.payload.page;
        state.hasMore = action.payload.items.length === PAGE_SIZE;
      })
      .addCase(fetchNotices.rejected, (state, action) => {
        state.status = "failed";
        state.error = action.payload;
      })
      // adding: the new notice goes to the top of the list
      .addCase(createNotice.fulfilled, (state, action) => {
        state.items.unshift(action.payload);
        if (state.items.length > PAGE_SIZE) state.items.pop();
      })
      // updating: swap the old copy for the one the backend returned
      .addCase(updateNotice.fulfilled, (state, action) => {
        const index = state.items.findIndex((n) => n.id === action.payload.id);
        if (index !== -1) state.items[index] = action.payload;
      })
      // deleting: drop the record from the list
      .addCase(deleteNotice.fulfilled, (state, action) => {
        state.items = state.items.filter((n) => n.id !== action.payload);
        state.error = null;
      })
      .addCase(deleteNotice.rejected, (state, action) => {
        state.error = action.payload;
      });
  },
});

export const { resetNotices } = noticesSlice.actions;
export default noticesSlice.reducer;
