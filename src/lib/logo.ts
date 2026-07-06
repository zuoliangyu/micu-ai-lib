// Deterministic project logo generator.
//
// Projects can opt into a real `logo` URL in project.yaml; when they don't,
// we synthesize a GitHub-default-avatar-style SVG from the project name so
// every project has a visual anchor in cards/lists/table/detail.
//
// Determinism matters: Astro static builds must produce identical output for
// identical input, so we use a plain string hash (djb2) — never Math.random
// or Date.now.

const PALETTE: { bg: string; fg: string }[] = [
  { bg: '#1f6feb', fg: '#ffffff' }, // blue
  { bg: '#238636', fg: '#ffffff' }, // green
  { bg: '#8957e5', fg: '#ffffff' }, // purple
  { bg: '#db6d28', fg: '#ffffff' }, // orange
  { bg: '#c71d23', fg: '#ffffff' }, // red
  { bg: '#0969da', fg: '#ffffff' }, // sky
  { bg: '#1b7c83', fg: '#ffffff' }, // teal
  { bg: '#6e40c9', fg: '#ffffff' }, // indigo
  { bg: '#bf8700', fg: '#ffffff' }, // gold
  { bg: '#0550ae', fg: '#ffffff' }, // deep blue
  { bg: '#0a7b83', fg: '#ffffff' }, // cyan
  { bg: '#a4112d', fg: '#ffffff' }, // crimson
];

function hash(str: string): number {
  // djb2 — small, fast, well-distributed for short strings.
  let h = 5381;
  for (let i = 0; i < str.length; i++) {
    h = ((h << 5) + h + str.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

function firstGlyph(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return '·';
  // First code point handles surrogate pairs (emoji, rare CJK ext).
  const cp = trimmed.codePointAt(0)!;
  const ch = String.fromCodePoint(cp);
  // ASCII letter → uppercase first letter.
  if (/^[A-Za-z]$/.test(ch)) return ch.toUpperCase();
  // Anything else (CJK, digit, symbol) → the glyph itself.
  // Digits/symbols are rare project-name leads; the color block still reads.
  return ch;
}

function escapeXml(s: string): string {
  return s.replace(/[<>&"']/g, (c) => {
    switch (c) {
      case '<': return '&lt;';
      case '>': return '&gt;';
      case '&': return '&amp;';
      case '"': return '&quot;';
      case "'": return '&apos;';
      default: return c;
    }
  });
}

/** Inline SVG string for a name-derived logo (no external request). */
export function logoSvg(name: string, size = 40): string {
  const palette = PALETTE[hash(name) % PALETTE.length];
  const glyph = escapeXml(firstGlyph(name));
  // font-size ~ 0.5 * size for a single glyph; centered via text-anchor.
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img" aria-label="${glyph}"><rect width="${size}" height="${size}" rx="${size * 0.22}" fill="${palette.bg}"/><text x="50%" y="50%" dy="0.07em" fill="${palette.fg}" font-family="Fraunces, 'Noto Serif SC', serif" font-size="${Math.round(size * 0.5)}" font-weight="600" text-anchor="middle" dominant-baseline="central">${glyph}</text></svg>`;
}

/** Pick the logo markup for a project: real <img> if logo URL set, else generated SVG. */
export function projectLogo(p: { name: string; logo?: string }, size = 40): string {
  if (p.logo) {
    return `<img class="logo-img" src="${p.logo}" alt="${p.name} logo" width="${size}" height="${size}" loading="lazy" decoding="async" />`;
  }
  return logoSvg(p.name, size);
}
