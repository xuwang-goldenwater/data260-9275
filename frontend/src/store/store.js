// The one Redux store for the whole app.
//
// reducer: { notices: ... } means the notices slice owns state.notices,
// so a page reads the list as state.notices.items.
import { configureStore } from "@reduxjs/toolkit";

import noticesReducer from "../features/notices/noticesSlice.js";

export const store = configureStore({
  reducer: {
    notices: noticesReducer,
  },
});
