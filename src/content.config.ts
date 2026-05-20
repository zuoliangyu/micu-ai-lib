import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

const projects = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/projects' }),
  schema: z.object({
    name: z.string(),
    summary: z.string().default(''),
    authors: z.array(z.string()).default([]),
    category: z.string().default('Other'),
    tags: z.array(z.string()).default([]),
    status: z.string().optional(),
    updated: z
      .union([z.string(), z.date()])
      .transform((v) => (typeof v === 'string' ? v : v.toISOString().slice(0, 10)))
      .optional(),
    cover: z.string().optional(),
    demo: z.string().optional(),
    links: z.record(z.string(), z.string()).optional(),
    host: z.string().default('github'),
    repo: z.string(),
    slug: z.string(),
    web_url: z.string().default(''),
    last_commit: z.string().optional(),
  }),
});

export const collections = { projects };
