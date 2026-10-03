/**
 * Google sign-in via top-level OAuth redirect (implicit ID-token flow).
 *
 * Why not the embedded "Sign in with Google" button: it is a third-party iframe
 * (`accounts.google.com/gsi/button`) and browsers that block embedded
 * third-party sign-in collapse it to a 0x0 placeholder with no error anywhere —
 * which reads exactly as "login with Google doesn't work". A top-level redirect
 * to Google works in every browser and returns the very same Google ID token,
 * which is posted to `/api/v1/auth/login` and verified server-side against the
 * OAuth client id (identity.py). The response only ever lands on the registered
 * redirect URI (the console origin), and the state/nonce round-trip binds the
 * response to this tab's request.
 */
const CLIENT_ID = (import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined) ?? "";
const REDIRECT_URI = typeof window === "undefined" ? "" : window.location.origin + "/";
const STATE_KEY = "brain.google.state";

export function googleSignInAvailable(): boolean {
  return !!CLIENT_ID;
}

function randomToken(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** The URL to navigate to (top-level) to start a Google sign-in.
 *
 * Call this at ACTIVATION time (a click), never during render: it mints and
 * stores the state/nonce pair that `consumeGoogleRedirect` checks on return. A
 * render-time call would overwrite the pair of an in-flight sign-in the moment
 * the return page paints its gate — before the exchange effect runs — and every
 * return would fail its own round-trip check. */
export function buildGoogleAuthUrl(): string {
  const state = randomToken();
  const nonce = randomToken();
  try {
    sessionStorage.setItem(STATE_KEY, JSON.stringify({ state, nonce }));
  } catch {
    /* Private mode: sign-in still works, just without the round-trip binding. */
  }
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    response_type: "id_token",
    scope: "openid email profile",
    state,
    nonce,
    prompt: "select_account",
  });
  return `https://accounts.google.com/o/oauth2/v2/auth?${params}`;
}

export type GoogleRedirectResult =
  | { kind: "token"; idToken: string }
  | { kind: "error"; message: string }
  | { kind: "none" };

/**
 * Consume a Google redirect response in the URL fragment exactly once.
 * The fragment is cleared before returning so the ID token never lingers in
 * history or the address bar.
 */
export function consumeGoogleRedirect(): GoogleRedirectResult {
  const raw = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  if (!raw.includes("id_token=") && !raw.includes("error=")) return { kind: "none" };
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
  const params = new URLSearchParams(raw);
  const error = params.get("error");
  if (error) {
    return { kind: "error", message: params.get("error_description") || `Google sign-in failed (${error}).` };
  }
  const idToken = params.get("id_token");
  if (!idToken) return { kind: "none" };
  try {
    const saved = JSON.parse(sessionStorage.getItem(STATE_KEY) || "null");
    sessionStorage.removeItem(STATE_KEY);
    if (!saved || saved.state !== params.get("state") || saved.nonce !== params.get("nonce")) {
      return { kind: "error", message: "Sign-in could not be verified. Try again." };
    }
  } catch {
    return { kind: "error", message: "Sign-in could not be verified. Try again." };
  }
  return { kind: "token", idToken };
}
