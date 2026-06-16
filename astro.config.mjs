import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://micu-ai-lib.netlify.app',
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
