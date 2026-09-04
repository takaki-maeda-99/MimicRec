import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const isDemo = process.env.VITE_DEMO === 'true'

export default defineConfig({
  base: isDemo ? '/MimicRec/' : '/',
  plugins: [react(), tailwindcss()],
  server: {
    // Lab workstations often run ROS, editors, and several dev servers at
    // once, exhausting Linux's inotify watch quota. Polling keeps `run.sh`
    // reliable without requiring a machine-wide sudo sysctl change.
    watch: {
      usePolling: process.env.MIMICREC_VITE_USE_POLLING !== '0',
      interval: 500,
    },
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
})
