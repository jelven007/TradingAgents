import { defineConfig } from 'vite';

export default defineConfig({
  base: '/web/',
  build: {
    outDir: '../src/tradingagents/web',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: { entryFileNames: 'app.js', assetFileNames: 'style.css', inlineDynamicImports: true },
    },
  },
  server: {
    proxy: Object.fromEntries(
      ['/auth', '/accounts', '/session', '/tasks', '/research', '/instruments', '/watchlist', '/demo', '/reports', '/experiments', '/predictions', '/operations', '/audit', '/controls', '/calls', '/settings']
        .map(path => [path, {
          target: 'http://127.0.0.1:8783',
          changeOrigin: true,
          configure(proxy) {
            proxy.on('proxyReq', req => {
              if (['http://127.0.0.1:5173', 'http://localhost:5173'].includes(req.getHeader('origin'))) {
                req.setHeader('origin', 'http://127.0.0.1:8783');
              }
            });
          },
        }]),
    ),
  },
});
