import { defineConfig } from 'astro/config';

// Netlify serves at the root; the GitHub Pages build overrides these via env
// (SITE_URL=https://zuoliangyu.github.io, BASE_PATH=/micu-ai-lib).
export default defineConfig({
  site: process.env.SITE_URL || 'https://micu-ai-lib.netlify.app',
  base: process.env.BASE_PATH || '/',
  trailingSlash: 'ignore',
  build: {
    format: 'directory',
  },
  markdown: {
    shikiConfig: {
      // dual theme: light renders inline, dark exposed as --shiki-dark CSS var
      themes: {
        light: 'github-light',
        dark: 'github-dark',
      },
      wrap: true,
    },
  },
});
