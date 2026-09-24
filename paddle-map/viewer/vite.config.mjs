import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { existsSync, createReadStream } from 'node:fs';
import { resolve, sep } from 'node:path';

const assets = resolve(import.meta.dirname, '../public');
function compressedTiles() {
  return {
    name: 'paddle-compressed-tiles',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const pathname = decodeURIComponent((req.url || '').split('?')[0]);
        if (!/^\/tiles\/\d+\/\d+\/\d+\.pbf$/.test(pathname)) return next();
        const file = resolve(assets, `.${pathname}`);
        if (!file.startsWith(assets + sep)) return next();
        const compressed = /\bgzip\b/.test(req.headers['accept-encoding'] || '') && existsSync(file+'.gz');
        if (!existsSync(file)) return next();
        res.setHeader('Content-Type', 'application/vnd.mapbox-vector-tile');
        res.setHeader('Cache-Control', 'public, max-age=3600');
        res.setHeader('Vary', 'Accept-Encoding');
        if (compressed) res.setHeader('Content-Encoding', 'gzip');
        createReadStream(file + (compressed ? '.gz' : '')).pipe(res);
      });
    }
  };
}

export default defineConfig({
  publicDir: '../public',
  build: {
    outDir: "dist/client",
  },
  optimizeDeps: {
    include: ["react", "react-dom/client"],
  },
  server: {
    host: "0.0.0.0",
    allowedHosts: ["terminal.local"],
    warmup: {
      clientFiles: ["./src/main.jsx"],
    },
  },
  plugins: [compressedTiles(), react()],
});
