import { useMemo, useSyncExternalStore } from "react";

import { createSessionListingsApi } from "../../api/listings";
import type { SessionStore } from "../../api/session";
import { ListingsPage } from "./ListingsPage";

/** Integration owner mounts this with the same volatile store passed to App. */
export function SessionListingsPage({ session }: { session: SessionStore }) {
  const state = useSyncExternalStore(session.subscribe, session.getState);
  const api = useMemo(() => createSessionListingsApi(session), [session]);
  return <ListingsPage
    session={state.status === "signed-in" ? { userId: state.user.id, role: state.user.role } : null}
    api={api}
  />;
}
