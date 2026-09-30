import { hasToken } from "./api";

export const liveViews = ["overview", "inbox", "brain", "ask", "studio", "activate", "sources", "analytics", "audit", "import"] as const;
export const previewViews = ["workspaces", "working-memory", "graph", "connectors", "api-keys", "agents", "requests", "insights", "turns", "proactivity", "settings"] as const;
export type View = typeof liveViews[number] | typeof previewViews[number];
export type Screen = "landing" | "login" | "console" | "demo";
export type Route = { screen: Screen; view: View; record?: string };

/** Non-secret build flag. Console release keeps landing off; later website release sets VITE_SHOW_LANDING=true. */
export const SHOW_LANDING = import.meta.env.VITE_SHOW_LANDING === "true";

const landingHashes = new Set(["#/", "#how-it-works", "#principles", "#agents", "#landing-main"]);

export function readRoute(): Route {
  const [hash, query = ""] = window.location.hash.split("?");
  const record = new URLSearchParams(query).get("record") ?? undefined;
  if (landingHashes.has(hash)) {
    return { screen: SHOW_LANDING ? "landing" : "login", view: "overview" };
  }
  if (hash === "#/login") return { screen: "login", view: "overview" };
  if (hash.startsWith("#/console/")) {
    const requested = hash.slice("#/console/".length) as View;
    return { screen: "console", view: [...liveViews, ...previewViews].includes(requested) ? requested : "overview", record };
  }
  if (hash.startsWith("#/demo/")) {
    const requested = hash.slice("#/demo/".length) as View;
    return { screen: "demo", view: [...liveViews, ...previewViews].includes(requested) ? requested : "overview", record };
  }
  if (hasToken()) return { screen: "console", view: "overview" };
  return { screen: SHOW_LANDING ? "landing" : "login", view: "overview" };
}

export function goTo(screen: Screen, view: View = "overview", record?: string) {
  if (screen === "landing" && !SHOW_LANDING) {
    window.location.hash = "#/login";
    return;
  }
  window.location.hash =
    screen === "landing"
      ? "#/"
      : screen === "login"
        ? "#/login"
        : `#/${screen}/${view}${record ? `?record=${encodeURIComponent(record)}` : ""}`;
}
