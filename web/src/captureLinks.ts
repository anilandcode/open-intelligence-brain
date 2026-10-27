/** What a share sheet, bookmarklet or shortcut handed the console, if anything. */
export type SharedCapture = { title: string; text: string; url: string; via: "share" | "clipper" };

const firstUrl = (value: string) => value.match(/https?:\/\/\S+/)?.[0] ?? "";

/**
 * Reads a share from the page URL. The phone share sheet (Web Share Target)
 * puts title/text/url in the query string; the bookmarklet puts them after
 * the hash route. Android often sends the link inside `text`, so it is moved
 * to `url` when `url` is empty.
 */
export function readSharedCapture(location: Pick<Location, "search" | "hash"> = window.location): SharedCapture | null {
  const hashQuery = location.hash.includes("?") ? location.hash.slice(location.hash.indexOf("?") + 1) : "";
  const sources: [string, SharedCapture["via"]][] = [[location.search.replace(/^\?/, ""), "share"], [hashQuery, "clipper"]];
  for (const [query, via] of sources) {
    const params = new URLSearchParams(query);
    if (!params.has("text") && !params.has("url")) continue;
    let text = (params.get("text") ?? "").trim();
    let url = (params.get("url") ?? "").trim();
    if (!url && firstUrl(text) && firstUrl(text) === text) { url = text; text = ""; }
    else if (!url) url = firstUrl(text);
    return { title: (params.get("title") ?? "").trim(), text, url, via };
  }
  return null;
}

/** A share target lands on `/?text=…`; route it to the capture view once a person is signed in. */
export function isShareLanding(search: string = window.location.search): boolean {
  const params = new URLSearchParams(search);
  return (params.has("text") || params.has("url")) && !params.has("session_uri") && !params.has("error");
}

/** Bookmarklet that opens the capture view with the page's title, link and selected text. */
export function bookmarklet(origin: string): string {
  const target = `${origin.replace(/\/$/, "")}/#/console/capture?`;
  return `javascript:(()=>{const q=new URLSearchParams({title:document.title,url:location.href,text:String(getSelection())});window.open(${JSON.stringify(target)}+q,"_blank")})()`;
}

type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  start: () => void;
  stop: () => void;
};

/** The browser's speech-to-text, where it has one (Chrome, Edge, Safari). Audio never reaches the Brain. */
export function speechRecognition(): (new () => Recognition) | null {
  const scope = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null;
}
