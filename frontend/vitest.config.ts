import { svelte } from '@sveltejs/vite-plugin-svelte';
import path from 'node:path';
import { defineConfig } from 'vitest/config';
export default defineConfig({
  plugins: [svelte({ hot: false })],
  resolve: {
    conditions: ['browser'],
    alias: {
      $lib: path.resolve('src/lib'),
      '$env/static/public': path.resolve('tests/stubs/env.ts'),
      '$app/navigation': path.resolve('tests/stubs/nav.ts'),
      '$app/state': path.resolve('tests/stubs/state.svelte.ts')
    }
  },
  test: { environment: 'jsdom', environmentOptions: { jsdom: { url: 'http://localhost:5173' } }, include: ['tests/**/*.test.ts'], testTimeout: 20000 }
});
