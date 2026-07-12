/// <reference types="vite/client" />
/// <reference types="cesium" />

export {};

declare global {
  interface Window {
    CESIUM_BASE_URL: string;
  }
}
