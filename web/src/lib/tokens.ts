export const tokens = {
  ink: '#0B1020',
  surface: '#131A2E',
  accent: '#00D9A8',
  amber: '#FFB800',
  danger: '#FF4D6D',
  success: '#22C55E',
  text: '#EAF0FF',
  muted: '#8B93B0',
  radius: {
    card: '14px',
    pill: '9999px',
  },
  fonts: {
    display: '"Space Grotesk", sans-serif',
    body: '"Inter", sans-serif',
  },
} as const;

export type DesignTokens = typeof tokens;
