import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const pilotTarget = loadEnv(mode, '.', 'P23_').P23_API_PROXY_TARGET;
  if (pilotTarget) {
    const target = /^http:\/\/127\.0\.0\.1:([1-9]\d{3,4})\/?$/.exec(pilotTarget);
    if (!target || Number(target[1]) < 1024 || Number(target[1]) > 65535) {
      throw new Error('P23_API_PROXY_TARGET must be an explicit loopback HTTP port');
    }
  }
  return {
  envDir: '.',
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: pilotTarget || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  };
});
