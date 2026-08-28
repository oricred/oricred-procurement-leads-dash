import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'pwa-192x192.png', 'pwa-512x512.png'],
      manifest: {
        name: 'Oricred — Procurement Intelligence',
        short_name: 'Oricred',
        description: 'Procurement intelligence and opportunity pipeline management',
        theme_color: '#1e1e2e',
        background_color: '#1e1e2e',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: '/pwa-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: '/pwa-512x512.png', sizes: '512x512', type: 'image/png' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,ico,woff2,woff,ttf}'],
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/fonts\.googleapis\.com\/.*/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'google-fonts-css',
              expiration: { maxEntries: 10, maxAgeSeconds: 60 * 60 * 24 * 365 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            urlPattern: /^https:\/\/fonts\.gstatic\.com\/.*/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'google-fonts',
              expiration: { maxEntries: 50, maxAgeSeconds: 60 * 60 * 24 * 365 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            // Reference data only — no personal data, safe to persist on disk.
            //
            // Everything else under /api/ is deliberately NOT cached. The
            // previous blanket /^\/api\// rule wrote lead and contact records
            // (names, direct numbers, personal email addresses of third
            // parties) into Cache Storage, where they survived logout and were
            // readable by the next user of a shared machine.
            //
            // Adding an endpoint here means asserting its response contains no
            // personal data. Caches named api-* are cleared on logout by
            // clearApiCaches() in src/services/api.ts.
            urlPattern: /^\/api\/(organizations|categories|tenders\/provinces)$/i,
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'api-reference',
              expiration: { maxEntries: 10, maxAgeSeconds: 60 * 60 * 24 },
              // Status 0 is an opaque response; never cache one.
              cacheableResponse: { statuses: [200] },
            },
          },
          {
            urlPattern: /^\/.*/i,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'app-shell',
              expiration: { maxEntries: 50, maxAgeSeconds: 60 * 60 * 24 },
              networkTimeoutSeconds: 5,
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
});
