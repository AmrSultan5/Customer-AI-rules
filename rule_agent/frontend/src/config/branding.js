/**
 * Centralized product identity.
 *
 * This app is a swappable placeholder brand for a generic multi-knowledge-base
 * analyst assistant — nothing here should be domain-specific. Per-deployment
 * flavor (which knowledge base, its vocabulary/name) comes from the active KB
 * descriptor at runtime (see `GET /api/kbs`), not from this file.
 *
 * `accent` documents the same value baked into `--accent` in
 * `src/styles/main.css` (dark theme). Keep the two in sync if you change the
 * brand color — CSS owns the actual cascade (including the derived
 * --accent-hover/--accent-glow/--accent-grad tokens for both themes), this
 * constant exists for any JS that needs the raw value.
 */
export const branding = {
  productName: 'Knowledge Analyst',
  shortName: 'Analyst',
  tagline: 'AI-powered knowledge base assistant',
  accent: '#6366F1',
}

export default branding
