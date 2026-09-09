const SERVER_KEY = "voxpersona_server_url";

/** Normalize to origin without trailing slash. */
export function normalizeServerUrl(input: string): string {
  let url = input.trim();
  if (!url) return "";
  if (!/^https?:\/\//i.test(url)) {
    url = `https://${url}`;
  }
  try {
    const parsed = new URL(url);
    return `${parsed.protocol}//${parsed.host}`;
  } catch {
    return url.replace(/\/+$/, "");
  }
}

export function getServerUrl(): string {
  return localStorage.getItem(SERVER_KEY) || "";
}

export function setServerUrl(url: string) {
  const normalized = normalizeServerUrl(url);
  if (!normalized) localStorage.removeItem(SERVER_KEY);
  else localStorage.setItem(SERVER_KEY, normalized);
  return normalized;
}

export function clearServerUrl() {
  localStorage.removeItem(SERVER_KEY);
}

/**
 * API root used by fetch helpers.
 * - Web (same host as cPanel site): empty → relative `/api/...`
 * - Android app: must point at hosted domain, e.g. https://voice.example.com
 */
export function apiRoot(): string {
  const stored = getServerUrl();
  if (stored) return stored;
  return "";
}

export function apiUrl(path: string): string {
  const root = apiRoot();
  if (!path.startsWith("/")) path = `/${path}`;
  return root ? `${root}${path}` : path;
}

export function isNativeApp(): boolean {
  try {
    // Avoid hard crash if Capacitor is not present in plain web builds.
    const cap = (window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } })
      .Capacitor;
    return !!cap?.isNativePlatform?.();
  } catch {
    return false;
  }
}

export function needsServerSetup(): boolean {
  if (isNativeApp()) return !getServerUrl();
  return false;
}
