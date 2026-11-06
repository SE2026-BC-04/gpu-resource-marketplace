import { useMemo, useSyncExternalStore } from "react";

import { createJobsApi } from "../../api/jobs";
import type { SessionStore } from "../../api/session";
import { JobsPage } from "./JobsPage";

/** Mount Jobs against the same volatile authentication store used by App and Listings. */
export function SessionJobsPage({ session }: { session: SessionStore }) {
  const state = useSyncExternalStore(session.subscribe, session.getState);
  const api = useMemo(() => createJobsApi(session), [session]);
  if (state.status !== "signed-in") return null;
  return <JobsPage api={api} user={state.user} allowSubmit />;
}
