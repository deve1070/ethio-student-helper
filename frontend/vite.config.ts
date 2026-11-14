import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

const OFFLINE_API_CACHE = 'esh-api' // also named in src/lib/auth.tsx, which clears it on logout
const OFFLINE_API_PATHS = [
  '/v1/auth/me',
  '/v1/notes/',
  '/v1/study-plan/week',
  '/v1/esslce/mistakes',
  '/v1/practice/mistakes',
  '/v1/progress/',
  '/v1/esslce/subjects',
  '/v1/esslce/units',
  '/v1/esslce/papers',
]

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.png', 'apple-touch-icon.png'],
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
        globPatterns: ['**/*.{js,css,html,svg,png,ico}'],
        // Read-only pages keep working offline: notes, the study plan, mistakes, progress and the
        // profile (without /auth/me the app can't get past its login gate at all). Network first,
        // so online students always get fresh data; the saved copy is used only when the network
        // fails or takes longer than 6s. Practice and AI help are never cached - answers are
        // graded and recorded on the server. The cache is cleared on logout (lib/auth.tsx).
        runtimeCaching: [
          {
            // anchored at the start of the URL: workbox only lets a RegExp route match a
            // cross-origin request (the API is on its own domain in production) from index 0
            urlPattern: new RegExp(`^https?://[^/]+(${OFFLINE_API_PATHS.join('|')})`),
            method: 'GET',
            handler: 'NetworkFirst',
            options: {
              cacheName: OFFLINE_API_CACHE,
              networkTimeoutSeconds: 6,
              expiration: { maxEntries: 300, maxAgeSeconds: 60 * 24 * 60 * 60 },
              cacheableResponse: { statuses: [200] },
            },
          },
        ],
      },
    }),
  ],
  server: {
    proxy: {
      '/v1': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
