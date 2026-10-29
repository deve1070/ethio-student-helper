import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'apple-touch-icon.png'],
      manifest: {
        name: 'Ethiopian Student Helper',
        short_name: 'Student Helper',
        description: 'Grade 9-12 textbook help and ESSLCE exam practice, grounded in your textbooks.',
        start_url: '/',
        display: 'standalone',
        background_color: '#0b1210',
        theme_color: '#0f3d35',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // API calls are never cached as "offline answers" (the project's own scope decision) -
        // only the app shell/static assets are. Runtime caching is added later only for the
        // narrow "view already-fetched questions offline" case, not blanket API caching.
        globPatterns: ['**/*.{js,css,html,svg,png,ico}'],
      },
    }),
  ],
  server: {
    proxy: {
      '/v1': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
