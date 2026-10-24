import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { createAuthApi } from "./api/auth";
import { createSessionStore } from "./api/session";
import { App } from "./ui/App";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Root element was not found");

// One volatile session per page load; API clients read its token via session.getAccessToken().
const session = createSessionStore(createAuthApi());

createRoot(root).render(
  <StrictMode>
    <App session={session} />
  </StrictMode>,
);
