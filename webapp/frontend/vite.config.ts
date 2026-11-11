import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Relative production assets let the same static build work at a repository
// Pages subpath and in a local preview. Local API development keeps root paths.
export default defineConfig(({ mode }) => ({
  base: mode === 'pages' ? './' : '/',
  plugins: [react()],
}))
