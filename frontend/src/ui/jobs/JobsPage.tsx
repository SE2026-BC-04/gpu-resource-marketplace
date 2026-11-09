import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import type { AuthUser } from "../../api/auth";
import {
  createJobSubmissionAttempt,
  jobsScopeForRole,
  JobsApiError,
  JOB_STATUSES,
} from "../../api/jobs";
import type { JobCollectionResponse, JobFailureReason, JobResponse, JobStatus, JobsApi, SubmitJobRequest } from "../../api/jobs";
import "./jobs.css";

const statusLabels: Record<JobStatus, string> = {
  QUEUED: "Đang chờ",
  RUNNING: "Đang chạy",
  COMPLETED: "Hoàn tất",
  FAILED: "Thất bại",
  CANCELLED: "Đã hủy",
};

const failureLabels: Record<JobFailureReason, string> = {
  WORKER_FAULT: "Lỗi Worker",
  JOB_FAULT: "Lỗi công việc",
  SYSTEM_FAULT: "Lỗi hệ thống",
};

const JOB_STATUS_POLL_INTERVAL_MS = 2000;
const JOB_STATUS_REQUEST_TIMEOUT_MS = 5000;
const JOB_STATUS_RETRY_DELAYS_MS = [1000, 2000, 4000] as const;
const MAX_CONSECUTIVE_STATUS_READ_FAILURES = 3;

function isPendingJobStatus(status: JobStatus): boolean {
  return status === "QUEUED" || status === "RUNNING";
}

function isTransientStatusReadFailure(error: unknown): boolean {
  if (error instanceof JobsApiError) return error.status === 0 || error.status >= 500;
  return error instanceof Error && error.name === "AbortError";
}

function safeError(error: unknown): { message: string; requestId?: string } {
  if (error instanceof JobsApiError) return { message: error.message, requestId: error.requestId };
  return { message: "Không thể xử lý yêu cầu lúc này." };
}

function ErrorNotice({ error, retry, retryLabel = "Thử lại" }: { error: unknown; retry?: () => void; retryLabel?: string }) {
  const detail = safeError(error);
  return (
    <div className="jobs-error" role="alert">
      <span>{detail.message}</span>
      {detail.requestId && <small>Mã yêu cầu: <code>{detail.requestId}</code></small>}
      {retry && <button type="button" onClick={retry}>{retryLabel}</button>}
    </div>
  );
}

export function JobStatusBadge({ status }: { status: JobStatus }) {
  return <span className={`job-status job-status--${status.toLowerCase()}`} role="status">{statusLabels[status]}</span>;
}

export function JobsList({
  jobs,
  loading,
  selectedId,
  onSelect,
}: {
  jobs: JobResponse[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (loading) return <p role="status">Đang tải danh sách công việc…</p>;
  if (jobs.length === 0) return <p className="jobs-empty">Chưa có công việc nào.</p>;
  return (
    <ul className="jobs-list" aria-label="Danh sách công việc">
      {jobs.map((job) => (
        <li key={job.id}>
          <button
            type="button"
            className="jobs-list-item"
            aria-current={selectedId === job.id ? "true" : undefined}
            onClick={() => onSelect(job.id)}
          >
            <span><code>{job.id}</code><small>Listing {job.listing_id}</small></span>
            <span><JobStatusBadge status={job.status} /><small>{job.gpu_count} GPU · {job.duration_seconds}s</small></span>
          </button>
        </li>
      ))}
    </ul>
  );
}

type DetailRequestContext = {
  jobId: string;
  requestKey: string;
  generation: number;
};

type CancelActionLifecycle = {
  busy: boolean;
  error: unknown | null;
  inFlight: boolean;
  needsReconciliation: boolean;
};

function newCancelActionLifecycle(): CancelActionLifecycle {
  return { busy: false, error: null, inFlight: false, needsReconciliation: false };
}

export function CancelJobAction({ job, api, requestContext, lifecycle, onLifecycleChange, onCancelled, onReconciled, onReconcileStart, onConflict }: {
  job: JobResponse;
  api: JobsApi;
  requestContext: DetailRequestContext;
  lifecycle: CancelActionLifecycle;
  onLifecycleChange: () => void;
  onCancelled: (job: JobResponse, context: DetailRequestContext) => void;
  onReconciled: (job: JobResponse, context: DetailRequestContext) => void;
  onReconcileStart: (context: DetailRequestContext) => DetailRequestContext;
  onConflict: () => void;
}) {
  function updateLifecycle(patch: Partial<CancelActionLifecycle>) {
    Object.assign(lifecycle, patch);
    onLifecycleChange();
  }

  async function reconcile() {
    if (lifecycle.inFlight) return;
    updateLifecycle({ inFlight: true, busy: true, error: null });
    const reconciliationContext = onReconcileStart(requestContext);
    try {
      const reconciledJob = await api.getJob(job.id);
      onReconciled(reconciledJob, reconciliationContext);
      updateLifecycle({ needsReconciliation: false });
    } catch (caught) {
      updateLifecycle({ needsReconciliation: true, error: caught });
    } finally {
      updateLifecycle({ inFlight: false, busy: false });
    }
  }

  if (job.status !== "QUEUED") return null;

  async function cancel() {
    if (lifecycle.inFlight || lifecycle.needsReconciliation) return;
    updateLifecycle({ inFlight: true, busy: true, error: null });
    try {
      const cancelledJob = await api.cancelJob(job.id);
      onCancelled(cancelledJob, requestContext);
      updateLifecycle({ error: null });
    } catch (caught) {
      if (caught instanceof JobsApiError && ((caught.status === 409 && caught.code === "JOB_NOT_CANCELLABLE") || caught.status === 0 || caught.status >= 500)) {
        updateLifecycle({ needsReconciliation: true });
        onConflict();
        updateLifecycle({ inFlight: false, busy: false });
        await reconcile();
      } else {
        updateLifecycle({ error: caught });
      }
    } finally {
      updateLifecycle({ inFlight: false, busy: false });
    }
  }

  return (
    <div className="jobs-action">
      {lifecycle.error !== null && <ErrorNotice error={lifecycle.error} retry={lifecycle.needsReconciliation ? reconcile : undefined} retryLabel="Tải lại trạng thái" />}
      <button type="button" className="jobs-danger" disabled={lifecycle.busy || lifecycle.needsReconciliation} onClick={cancel}>
        {lifecycle.busy ? "Đang hủy…" : "Hủy công việc"}
      </button>
    </div>
  );
}

export function JobDetail({ job, role, api, requestContext, cancelLifecycle, onCancelLifecycleChange, onCancelled, onReconciled, onReconcileStart, onConflict }: {
  job: JobResponse;
  role: AuthUser["role"];
  api: JobsApi;
  requestContext: DetailRequestContext;
  cancelLifecycle: CancelActionLifecycle;
  onCancelLifecycleChange: () => void;
  onCancelled: (job: JobResponse, context: DetailRequestContext) => void;
  onReconciled: (job: JobResponse, context: DetailRequestContext) => void;
  onReconcileStart: (context: DetailRequestContext) => DetailRequestContext;
  onConflict: () => void;
}) {
  return (
    <section className="job-detail" aria-label="Chi tiết công việc">
      <div className="job-detail-heading"><h3>Chi tiết công việc</h3><JobStatusBadge status={job.status} /></div>
      <dl>
        <dt>Job ID</dt><dd><code>{job.id}</code></dd>
        <dt>Listing ID</dt><dd><code>{job.listing_id}</code></dd>
        {role === "CLIENT" && job.worker_id && <><dt>Worker ID</dt><dd><code>{job.worker_id}</code></dd></>}
        <dt>GPU</dt><dd>{job.gpu_count}</dd>
        <dt>Thời lượng</dt><dd>{job.duration_seconds} giây</dd>
        <dt>Gửi lúc</dt><dd>{job.submitted_at}</dd>
        {job.started_at && <><dt>Bắt đầu</dt><dd>{job.started_at}</dd></>}
        {job.terminal_at && <><dt>Kết thúc</dt><dd>{job.terminal_at}</dd></>}
        {job.status === "FAILED" && job.failure_reason && <><dt>Lý do</dt><dd>{failureLabels[job.failure_reason]}</dd></>}
      </dl>
      {role === "CLIENT" && <CancelJobAction
        key={job.id}
        job={job}
        api={api}
        requestContext={requestContext}
        lifecycle={cancelLifecycle}
        onLifecycleChange={onCancelLifecycleChange}
        onCancelled={onCancelled}
        onReconciled={onReconciled}
        onReconcileStart={onReconcileStart}
        onConflict={onConflict}
      />}
    </section>
  );
}

function uncertainSubmit(error: unknown): boolean {
  return error instanceof JobsApiError && (error.status === 0 || error.status >= 500);
}

export function SubmitJobForm({ onSubmit, onSubmitted }: {
  onSubmit: (attempt: ReturnType<typeof createJobSubmissionAttempt>) => Promise<JobResponse>;
  onSubmitted: (job: JobResponse) => void;
}) {
  const [listingId, setListingId] = useState("");
  const [gpuCount, setGpuCount] = useState("1");
  const [duration, setDuration] = useState("60");
  const [busy, setBusy] = useState(false);
  const [lastAttempt, setLastAttempt] = useState<ReturnType<typeof createJobSubmissionAttempt> | null>(null);
  const [uncertainAttempt, setUncertainAttempt] = useState<ReturnType<typeof createJobSubmissionAttempt> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const inFlight = useRef(false);

  async function sendAttempt(attempt: ReturnType<typeof createJobSubmissionAttempt>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const job = await onSubmit(attempt);
      setLastAttempt(null);
      setUncertainAttempt(null);
      setSuccess(`Đã gửi công việc ${job.id}. Trạng thái hiện tại: ${statusLabels[job.status]}.`);
      onSubmitted(job);
    } catch (caught) {
      setError(caught);
      setLastAttempt(attempt);
      setUncertainAttempt(uncertainSubmit(caught) ? attempt : null);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current || uncertainAttempt) return;
    setError(null);
    try {
      const request: SubmitJobRequest = {
        listing_id: listingId,
        gpu_count: Number(gpuCount),
        duration_seconds: Number(duration),
      };
      const prior = lastAttempt;
      const attempt = prior &&
        prior.request.listing_id === request.listing_id &&
        prior.request.gpu_count === request.gpu_count &&
        prior.request.duration_seconds === request.duration_seconds
        ? prior
        : createJobSubmissionAttempt(request);
      void sendAttempt(attempt);
    } catch {
      setError(new JobsApiError("VALIDATION_ERROR", 422));
    }
  }

  return (
    <section className="submit-job" aria-labelledby="submit-job-title">
      <h2 id="submit-job-title">Gửi công việc</h2>
      <p>Chọn Listing ID và thông số yêu cầu. API sẽ xác thực trạng thái Listing, quyền sở hữu và dung lượng.</p>
      <form onSubmit={submit} noValidate>
        <label>Listing ID (UUIDv4)
          <input value={listingId} onChange={(event) => setListingId(event.target.value)} disabled={busy || !!uncertainAttempt} required />
        </label>
        <div className="submit-job-numbers">
          <label>Số GPU
            <input type="number" min="1" max="2147483647" step="1" value={gpuCount} onChange={(event) => setGpuCount(event.target.value)} disabled={busy || !!uncertainAttempt} required />
          </label>
          <label>Thời lượng (giây)
            <input type="number" min="1" max="2147483647" step="1" value={duration} onChange={(event) => setDuration(event.target.value)} disabled={busy || !!uncertainAttempt} required />
          </label>
        </div>
        <button type="submit" disabled={busy || !!uncertainAttempt}>{busy ? "Đang gửi…" : "Gửi công việc"}</button>
      </form>
      {error !== null && <ErrorNotice error={error} />}
      {success && <p className="jobs-success" role="status">{success}</p>}
      {uncertainAttempt && (
        <div className="jobs-uncertain" role="group" aria-label="Gửi lại cùng yêu cầu">
          <p>Chưa xác định máy chủ đã ghi nhận yêu cầu hay chưa. Giữ nguyên trang và gửi lại đúng nội dung với cùng khóa để tránh tạo Job trùng.</p>
          <button type="button" disabled={busy} onClick={() => void sendAttempt(uncertainAttempt)}>
            {busy ? "Đang thử lại…" : "Thử lại cùng yêu cầu"}
          </button>
        </div>
      )}
    </section>
  );
}

export function JobsPage({ api, user, allowSubmit = true }: { api: JobsApi; user: AuthUser; allowSubmit?: boolean }) {
  const emptyCollection: JobCollectionResponse = { items: [], next_cursor: null };
  const [listResult, setListResult] = useState<{
    key: string;
    collection: JobCollectionResponse;
    error: unknown | null;
  } | null>(null);
  const [statusFilter, setStatusFilter] = useState<JobStatus | "">("");
  const [cursor, setCursor] = useState<string | undefined>();
  const [previousCursors, setPreviousCursors] = useState<Array<string | undefined>>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailResult, setDetailResult] = useState<{
    key: string;
    job: JobResponse | null;
    error: unknown | null;
    pollingMessage?: string | null;
  } | null>(null);
  const [reloadVersion, setReloadVersion] = useState(0);
  const [detailReloadVersion, setDetailReloadVersion] = useState(0);
  const [detailGeneration, setDetailGeneration] = useState(0);
  const listRequestKey = JSON.stringify([user.id, user.role, statusFilter, cursor ?? null, reloadVersion]);
  const detailRequestKey = JSON.stringify([user.id, user.role, selectedId, detailReloadVersion]);
  const detailRequestKeyRef = useRef(detailRequestKey);
  const selectedIdRef = useRef(selectedId);
  const detailGenerationRef = useRef(0);
  const cancelLifecyclesRef = useRef(new Map<string, CancelActionLifecycle>());
  const [, refreshCancelLifecycles] = useState(0);
  detailRequestKeyRef.current = detailRequestKey;
  selectedIdRef.current = selectedId;
  const collection = listResult?.key === listRequestKey ? listResult.collection : emptyCollection;
  const listError = listResult?.key === listRequestKey ? listResult.error : null;
  const listLoading = listResult?.key !== listRequestKey;
  const detail = detailResult?.key === detailRequestKey ? detailResult.job : null;
  const detailError = detailResult?.key === detailRequestKey ? detailResult.error : null;
  const pollingMessage = detailResult?.key === detailRequestKey ? detailResult.pollingMessage ?? null : null;
  const detailLoading = selectedId !== null && detailResult?.key !== detailRequestKey;

  useEffect(() => {
    const controller = new AbortController();
    api.listJobs({ scope: jobsScopeForRole(user.role), limit: 20, cursor, ...(statusFilter ? { status: statusFilter } : {}) }, controller.signal)
      .then((collection) => { if (!controller.signal.aborted) setListResult({ key: listRequestKey, collection, error: null }); })
      .catch((error: unknown) => { if (!controller.signal.aborted) setListResult({ key: listRequestKey, collection: emptyCollection, error }); });
    return () => controller.abort();
  }, [api, user.id, user.role, cursor, statusFilter, reloadVersion]);

  useEffect(() => {
    if (!selectedId) return;
    const jobId = selectedId;
    const controller = new AbortController();
    const requestKey = detailRequestKey;
    const requestGeneration = ++detailGenerationRef.current;
    let currentJob = detailResult?.key === requestKey ? detailResult.job : null;
    let consecutiveFailures = 0;
    let scheduledPoll: number | undefined;
    let disposed = false;
    setDetailGeneration(requestGeneration);
    const isCurrentRequest = () =>
      !disposed &&
      !controller.signal.aborted &&
      selectedIdRef.current === jobId &&
      detailRequestKeyRef.current === requestKey &&
      detailGenerationRef.current === requestGeneration;

    function schedulePoll(delay: number) {
      if (disposed || controller.signal.aborted || scheduledPoll !== undefined) return;
      scheduledPoll = window.setTimeout(() => {
        scheduledPoll = undefined;
        void readDetail();
      }, delay);
    }

    async function readDetail() {
      if (!isCurrentRequest()) return;
      const requestController = new AbortController();
      let timeout: number | undefined;
      let rejectTimeout!: (reason: unknown) => void;
      let rejectLifecycleAbort!: (reason: unknown) => void;
      const timeoutPromise = new Promise<never>((_, reject) => { rejectTimeout = reject; });
      const lifecycleAbort = new Promise<never>((_, reject) => { rejectLifecycleAbort = reject; });
      const abortRequest = () => {
        requestController.abort();
        rejectLifecycleAbort(new Error("Job status request was cancelled."));
      };
      controller.signal.addEventListener("abort", abortRequest, { once: true });
      if (controller.signal.aborted) abortRequest();
      timeout = window.setTimeout(() => {
        rejectTimeout(new JobsApiError("NETWORK_ERROR", 0));
        requestController.abort();
      }, JOB_STATUS_REQUEST_TIMEOUT_MS);

      try {
        const job = await Promise.race([
          api.getJob(jobId, requestController.signal),
          timeoutPromise,
          lifecycleAbort,
        ]);
        if (!isCurrentRequest()) return;
        if (job.id !== jobId) throw new JobsApiError("INVALID_RESPONSE", 502);
        currentJob = job;
        consecutiveFailures = 0;
        setDetailResult({ key: requestKey, job, error: null, pollingMessage: null });
        if (isPendingJobStatus(job.status)) schedulePoll(JOB_STATUS_POLL_INTERVAL_MS);
      } catch (error: unknown) {
        if (!isCurrentRequest()) return;
        if (isTransientStatusReadFailure(error)) {
          consecutiveFailures += 1;
          if (consecutiveFailures > MAX_CONSECUTIVE_STATUS_READ_FAILURES) {
            setDetailResult({ key: requestKey, job: currentJob, error, pollingMessage: null });
            return;
          }
          const retryDelay = JOB_STATUS_RETRY_DELAYS_MS[consecutiveFailures - 1];
          setDetailResult({
            key: requestKey,
            job: currentJob,
            error: null,
            pollingMessage: `Không thể cập nhật trạng thái. Đang thử lại (${consecutiveFailures}/${MAX_CONSECUTIVE_STATUS_READ_FAILURES}).`,
          });
          schedulePoll(retryDelay);
          return;
        }
        setDetailResult({ key: requestKey, job: currentJob, error, pollingMessage: null });
      } finally {
        if (timeout !== undefined) window.clearTimeout(timeout);
        controller.signal.removeEventListener("abort", abortRequest);
        requestController.abort();
      }
    }

    void readDetail();
    return () => {
      disposed = true;
      if (scheduledPoll !== undefined) window.clearTimeout(scheduledPoll);
      controller.abort();
    };
  }, [api, user.id, user.role, selectedId, detailReloadVersion]);

  function changeFilter(value: JobStatus | "") {
    setStatusFilter(value);
    setCursor(undefined);
    setPreviousCursors([]);
  }

  function nextPage() {
    if (!collection.next_cursor) return;
    setPreviousCursors((previous) => [...previous, cursor]);
    setCursor(collection.next_cursor);
  }

  function previousPage() {
    if (previousCursors.length === 0) return;
    setCursor(previousCursors[previousCursors.length - 1]);
    setPreviousCursors((previous) => previous.slice(0, -1));
  }

  function submitSucceeded(job: JobResponse) {
    const nextDetailReloadVersion = detailReloadVersion + 1;
    const nextKey = JSON.stringify([user.id, user.role, job.id, nextDetailReloadVersion]);
    detailGenerationRef.current += 1;
    setDetailGeneration(detailGenerationRef.current);
    detailRequestKeyRef.current = nextKey;
    selectedIdRef.current = job.id;
    setSelectedId(job.id);
    setDetailResult({ key: nextKey, job, error: null });
    setDetailReloadVersion(nextDetailReloadVersion);
    setReloadVersion((version) => version + 1);
  }

  function isCurrentDetailRequest(context: DetailRequestContext): boolean {
    return context.jobId === selectedIdRef.current &&
      context.requestKey === detailRequestKeyRef.current &&
      context.generation === detailGenerationRef.current;
  }

  function cancelled(job: JobResponse, context: DetailRequestContext) {
    if (job.id === context.jobId && isCurrentDetailRequest(context)) {
      setDetailResult({ key: context.requestKey, job, error: null });
    }
    setReloadVersion((version) => version + 1);
  }

  function reconciled(job: JobResponse, context: DetailRequestContext) {
    if (job.id === context.jobId && isCurrentDetailRequest(context)) {
      setDetailResult({ key: context.requestKey, job, error: null });
    }
  }

  function beginReconciliation(context: DetailRequestContext): DetailRequestContext {
    if (!isCurrentDetailRequest(context)) return context;
    const generation = ++detailGenerationRef.current;
    setDetailGeneration(generation);
    return { ...context, generation };
  }

  function cancelLifecycleFor(jobId: string): CancelActionLifecycle {
    let lifecycle = cancelLifecyclesRef.current.get(jobId);
    if (!lifecycle) {
      lifecycle = newCancelActionLifecycle();
      cancelLifecyclesRef.current.set(jobId, lifecycle);
    }
    return lifecycle;
  }

  function reloadSelectedDetail() {
    const nextVersion = detailReloadVersion + 1;
    const nextKey = JSON.stringify([user.id, user.role, selectedId, nextVersion]);
    detailGenerationRef.current += 1;
    setDetailGeneration(detailGenerationRef.current);
    detailRequestKeyRef.current = nextKey;
    setDetailReloadVersion(nextVersion);
  }

  function selectJob(id: string) {
    const nextKey = JSON.stringify([user.id, user.role, id, detailReloadVersion]);
    detailGenerationRef.current += 1;
    setDetailGeneration(detailGenerationRef.current);
    detailRequestKeyRef.current = nextKey;
    selectedIdRef.current = id;
    setSelectedId(id);
  }

  return (
    <section className="jobs-page" aria-labelledby="jobs-page-title">
      <header className="jobs-page-header">
        <div><p className="jobs-eyebrow">GPU Resource Marketplace</p><h1 id="jobs-page-title">{user.role === "CLIENT" ? "My Jobs" : user.role === "WORKER" ? "Assigned Jobs" : "All Jobs"}</h1></div>
        <span className="jobs-role">{user.role}</span>
      </header>
      {user.role === "CLIENT" && allowSubmit && <SubmitJobForm key={user.id} onSubmit={(attempt) => api.submitJob(attempt)} onSubmitted={submitSucceeded} />}
      {user.role === "CLIENT" && !allowSubmit && <p className="jobs-muted">Gửi Job đang chờ hoàn tất các gate TX-SUBMIT đã được ghi trong handoff.</p>}
      <section className="jobs-browser" aria-labelledby="jobs-list-title">
        <div className="jobs-section-heading"><h2 id="jobs-list-title">Công việc</h2>
          <label>Lọc trạng thái
            <select value={statusFilter} onChange={(event) => changeFilter(event.target.value as JobStatus | "")}>
              <option value="">Tất cả</option>
              {JOB_STATUSES.map((status) => <option key={status} value={status}>{statusLabels[status]}</option>)}
            </select>
          </label>
        </div>
        {listError !== null && <ErrorNotice
          error={listError}
          retry={() => {
            if (listError instanceof JobsApiError && listError.code === "INVALID_CURSOR") {
              setCursor(undefined);
              setPreviousCursors([]);
            }
            setReloadVersion((version) => version + 1);
          }}
          retryLabel={listError instanceof JobsApiError && listError.code === "INVALID_CURSOR" ? "Tải lại từ đầu" : undefined}
        />}
        <JobsList jobs={collection.items} loading={listLoading} selectedId={selectedId} onSelect={selectJob} />
        <nav className="jobs-pagination" aria-label="Phân trang công việc">
          <button type="button" onClick={previousPage} disabled={listLoading || previousCursors.length === 0}>Trang trước</button>
          <button type="button" onClick={nextPage} disabled={listLoading || !collection.next_cursor}>Trang tiếp</button>
        </nav>
      </section>
      <section className="jobs-detail-panel" aria-live="polite">
        {detailLoading && <p role="status">Đang tải chi tiết…</p>}
        {pollingMessage && <p role="status">{pollingMessage}</p>}
        {detailError !== null && <ErrorNotice error={detailError} retry={reloadSelectedDetail} />}
        {detail && <JobDetail
          key={detail.id}
          job={detail}
          role={user.role}
          api={api}
          requestContext={{ jobId: detail.id, requestKey: detailRequestKey, generation: detailGeneration }}
          cancelLifecycle={cancelLifecycleFor(detail.id)}
          onCancelLifecycleChange={() => refreshCancelLifecycles((version) => version + 1)}
          onCancelled={cancelled}
          onReconciled={reconciled}
          onReconcileStart={beginReconciliation}
          onConflict={() => setReloadVersion((version) => version + 1)}
        />}
      </section>
    </section>
  );
}
