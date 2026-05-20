import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://micu-ai-lib.netlify.app',
  trailingSlash: 'ignore',
  build: {
    format: 'directory',
  },
});
