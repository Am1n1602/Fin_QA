import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/finqa-v2/",
  plugins: [react()],
  server: {
    port: 5174,
  },
});
