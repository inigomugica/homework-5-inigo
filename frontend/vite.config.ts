import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// `npm run dev` serves the desk on http://localhost:5173 and opens it in the browser.
// The backend (FastAPI on :8000) allows this origin via CORS.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, open: true },
})
