import react from '@vitejs/plugin-react';
import { loadEnv } from 'vite';
import { defineConfig } from 'vitest/config';
import { buildConfig } from './server/runtime-config.mjs';

export default defineConfig(({ mode }) => ({
  plugins: [
    react(),
    {
      name: 'public-runtime-config',
      configureServer(server) {
        server.middlewares.use('/config.json', (_req, res) => {
          res.setHeader('Content-Type', 'application/json');
          res.setHeader('Cache-Control', 'no-store');
          try {
            res.end(
              JSON.stringify(
                buildConfig({
                  ...loadEnv(mode, process.cwd(), ''),
                  ...process.env,
                }),
              ),
            );
          } catch {
            res.statusCode = 503;
            res.end(
              JSON.stringify({
                error: 'Runtime configuration is incomplete. See web/README.md.',
              }),
            );
          }
        });
      },
    },
  ],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('/node_modules/@azure/')) return 'identity';
          if (id.includes('/node_modules/@fluentui/') || id.includes('/node_modules/@griffel/'))
            return 'fluent';
          if (
            id.includes('/node_modules/react/') ||
            id.includes('/node_modules/react-dom/') ||
            id.includes('/node_modules/scheduler/')
          )
            return 'react';
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    restoreMocks: true,
  },
}));
