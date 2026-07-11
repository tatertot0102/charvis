/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_JARVIS_TOKEN?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
