/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  /** Non-secret: when "true", public marketing landing is enabled. Default off for console releases. */
  readonly VITE_SHOW_LANDING?: string;
  /** Non-secret: Cloud Run console origin for marketing-site CTAs. */
  readonly VITE_CONSOLE_URL?: string;
  /** Non-secret: Vercel marketing origin for console "back to home". */
  readonly VITE_SITE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
