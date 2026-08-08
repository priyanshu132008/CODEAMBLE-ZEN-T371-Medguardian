import type { MetadataRoute } from 'next';

/**
 * PWA Web App Manifest — makes MedGuardian installable on mobile devices.
 * Next.js auto-discovers this file convention and emits `<link rel="manifest">`.
 *
 * Theme + background use the Deep Navy command-center palette (#0f172a / #0b0f17)
 * so the installed app's splash + chrome match the in-app aesthetic.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'MedGuardian',
    short_name: 'MedGuardian',
    description:
      'Enterprise Clinical Orchestration & Instant TPA Claim Processing — multi-agent AI companion for post-discharge patient care.',
    start_url: '/',
    display: 'standalone',
    orientation: 'portrait-primary',
    background_color: '#0b0f17',
    theme_color: '#0f172a',
    categories: ['health', 'medical', 'productivity', 'finance'],
    icons: [
      {
        src: '/favicon.ico',
        sizes: 'any',
        type: 'image/x-icon',
      },
      {
        // Inline SVG shield icon used as the installable icon (no asset pipeline
        // dependency). purpose monochrome + any keeps maskable + normal contexts.
        src: '/icon.svg',
        sizes: '512x512',
        type: 'image/svg+xml',
        purpose: 'any',
      },
    ],
  };
}