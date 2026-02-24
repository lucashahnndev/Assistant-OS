import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

import { loadEnv } from 'vite'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, process.cwd(), '');
    const apiTarget = env.VITE_API_URL || 'http://localhost:8000';
    const port = parseInt(env.VITE_PORT) || 5173;
    const host = env.VITE_HOST || 'localhost';

    return {
        plugins: [react()],
        server: {
            host: host,
            port: port,
            proxy: {
                '/api': {
                    target: apiTarget,
                    changeOrigin: true
                }
            }
        }
    }
})
