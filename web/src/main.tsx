import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "@fontsource/figtree/latin-400.css";
import "@fontsource/figtree/latin-500.css";
import "@fontsource/figtree/latin-600.css";
import "@fontsource/geist-sans/latin-400.css";
import "@fontsource/geist-sans/latin-500.css";
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "@fontsource/inter/latin-600.css";
import "@fontsource/inter/latin-700.css";
import "@fontsource/source-serif-4/latin-400.css";
import "@fontsource/source-serif-4/latin-400-italic.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-600.css";
import "./tokens.css";
import "./primitives.css";
import "./shell.css";
import "./views.css";
import "./flows.css";
import "./system.css";
import "./refine.css";
import "./product.css";
import "./console-theme.css";
import "./caret.css";
import "./landing.css";
// Arc loads last so its semantic tokens win the few shared names, and its
// glue maps the Geist/Inter faces every Arc item expects.
import "./components/arc/foundation.css";
import "./arc-theme.css";
import "./gate.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
