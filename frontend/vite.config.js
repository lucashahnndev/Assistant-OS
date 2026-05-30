import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import fs from 'node:fs'
import path from 'node:path'

import { loadEnv } from 'vite'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, process.cwd(), '');
    const apiTarget = env.VITE_API_URL || 'https://127.0.0.1:8000';
    const port = parseInt(env.VITE_PORT) || 5173;
    const host = env.VITE_HOST || '0.0.0.0';
    const httpsEnabled = (env.VITE_HTTPS || 'true').toLowerCase() === 'true';
    const certPath = env.VITE_SSL_CERT_FILE
        ? path.resolve(env.VITE_SSL_CERT_FILE)
        : path.resolve(process.cwd(), '../data/certs/localhost.crt');
    const keyPath = env.VITE_SSL_KEY_FILE
        ? path.resolve(env.VITE_SSL_KEY_FILE)
        : path.resolve(process.cwd(), '../data/certs/localhost.key');
    const httpsConfig = httpsEnabled && fs.existsSync(certPath) && fs.existsSync(keyPath)
        ? { cert: fs.readFileSync(certPath), key: fs.readFileSync(keyPath) }
        : false;

    return {
        plugins: [
            react(),
            VitePWA({
                registerType: 'autoUpdate',
                // Manifest is served dynamically by the backend (/api/manifest.webmanifest)
                manifest: false,
                // Don't auto-inject a <link rel="manifest"> or a SW registration script
                // — our index.html already has the correct link and the SW auto-registers.
                injectRegister: null,
                // Disable completely in dev mode to avoid 404s on localhost:5173
                devOptions: { enabled: false },
                workbox: {
                    globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
                    navigateFallback: '/index.html',
                    navigateFallbackDenylist: [/^\/api/, /^\/ws/, /^\/manifest\.webmanifest/],
                    runtimeCaching: [
                        {
                            urlPattern: /\.(?:png|jpg|jpeg|svg|gif|webp|woff2?)$/,
                            handler: 'CacheFirst',
                            options: { cacheName: 'atlas-assets', expiration: { maxEntries: 60, maxAgeSeconds: 86400 } }
                        }
                    ]
                }
            })
        ],
        server: {
            host: host,
            port: port,
            https: httpsConfig,
            proxy: {
                '/api': {
                    target: apiTarget,
                    changeOrigin: true,
                    secure: false,
                },
                // Redirect bare /manifest.webmanifest (auto-injected by some PWA tools) to the backend route
                '/manifest.webmanifest': {
                    target: apiTarget,
                    changeOrigin: true,
                    secure: false,
                    rewrite: () => '/api/manifest.webmanifest',
                },
                '/ws': {
                    target: apiTarget,
                    changeOrigin: true,
                    secure: false,
                    ws: true,
                },
            }
        },
        preview: {
            host: host,
            port: port,
            https: httpsConfig,
            proxy: {
                '/api': {
                    target: apiTarget,
                    changeOrigin: true,
                    secure: false,
                    configure: (proxy, _options) => {
                        proxy.on('error', (err, _req, _res) => {
                            console.log('preview proxy error', err);
                        });
                        proxy.on('proxyReq', (proxyReq, req, _res) => {
                            console.log('Preview Sending Request to the Target:', req.method, req.url);
                        });
                        proxy.on('proxyRes', (proxyRes, req, _res) => {
                            console.log('Preview Received Response from the Target:', proxyRes.statusCode, req.url);
                        });
                    },
                },
                '/ws': {
                    target: apiTarget,
                    changeOrigin: true,
                    secure: false,
                    ws: true,
                    configure: (proxy, _options) => {
                        proxy.on('error', (err, _req, _res) => {
                            console.log('preview ws proxy error', err);
                        });
                    },
                },
            }
        }
    }
})
