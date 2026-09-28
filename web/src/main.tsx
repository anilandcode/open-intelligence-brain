import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./tokens.css";
import "./primitives.css";
import "./shell.css";
import "./views.css";
import "./flows.css";
import "./system.css";
import "./refine.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

