import { useSyncExternalStore } from "react";

import type { SessionStore } from "../api/session";
import { AccountPanel } from "./auth/AccountPanel";
import { LoginForm } from "./auth/LoginForm";
import "./auth/auth.css";

export function App({ session }: { session: SessionStore }) {
  const state = useSyncExternalStore(session.subscribe, session.getState);

  return (
    <main className="page-shell">
      <section className="welcome-card" aria-labelledby="welcome-title">
        <span className="eyebrow">A shared computing workspace</span>
        <h1 id="welcome-title">GPU Resource Marketplace</h1>
        <p>
          A place to discover and share GPU resources. The marketplace is being prepared.
        </p>
        {state.status === "signed-in"
          ? <AccountPanel store={session} user={state.user} />
          : <LoginForm store={session} reason={state.reason} />}
        <span className="status"><span aria-hidden="true" /> Development preview</span>
      </section>
    </main>
  );
}
