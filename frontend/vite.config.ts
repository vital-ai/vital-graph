import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import flowbiteReact from "flowbite-react/plugin/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), flowbiteReact()],
  server: {
    // Fix for delayed HMR updates
    watch: {
      usePolling: true,
      interval: 1000,
    },
    hmr: {
      overlay: true,
    },
    proxy: {
      // Proxy API requests to FastAPI backend
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        secure: false,
        ws: true,  // Enable WebSocket proxy support
      },
      '/health': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        secure: false,
      },
      // Images are now served directly from frontend/images directory
    },
  },
  build: {
    // Wipe the output dir on every build so old content-hashed bundles don't
    // pile up (they'd otherwise be copied into the packaged app and bloat the
    // wheel). Explicit because the deploy step copies dist elsewhere.
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-flowbite': ['flowbite-react'],
          'vendor-kg-model': ['@vital-ai/vital-kg-model-ts'],
        },
      },
    },
    chunkSizeWarningLimit: 600,
  },
  // Force dependency pre-bundling refresh
  optimizeDeps: {
    force: true,
  },
});
