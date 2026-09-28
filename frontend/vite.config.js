import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// React dev server on 5173. The API runs separately on PORT_BASE 8275;
// see src/api/client.js.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
});
