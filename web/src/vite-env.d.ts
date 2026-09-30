/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  /** When "true", public landing routes are enabled. Console-first releases leave this unset/false. */
  readonly VITE_SHOW_LANDING?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
