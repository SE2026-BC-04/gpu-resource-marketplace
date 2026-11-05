import { useEffect, useRef, useState } from "react";

import type { Listing, ListingInput, ListingScope, ListingStatus, ListingsApi, UserRole } from "../../api/listings";
import { ListingForm } from "./ListingForm";
import "./listings.css";

export interface ListingsSession { userId: string; role: UserRole }
interface Props { session: ListingsSession | null; api: ListingsApi }
type Editor = { kind: "create" } | { kind: "edit"; listing: Listing };

/** The GPU-003 shell supplies its real current-user state and auth-aware API. */
export function ListingsPage({ session, api }: Props) {
  if (!session) return <section className="listings-shell"><h1>GPU Listings</h1><p>Vui lòng đăng nhập để xem GPU Listings.</p></section>;
  // A different user/role must never see the preceding user's mine/details/form.
  return <Workspace key={`${session.userId}:${session.role}`} session={session} api={api} />;
}

function failureMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Không thể tải dữ liệu.";
}

function Workspace({ session, api }: { session: ListingsSession; api: ListingsApi }) {
  const [scope, setScope] = useState<ListingScope>("marketplace");
  const [status, setStatus] = useState<ListingStatus | "">("");
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [items, setItems] = useState<Listing[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Listing | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [busy, setBusy] = useState(false);
  const mutationLock = useRef(false);
  const mutationController = useRef<AbortController | null>(null);
  const cursor = cursors[cursors.length - 1];

  useEffect(() => () => mutationController.current?.abort(), []);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    setItems([]);
    setNextCursor(null);
    api.list({ scope, ...(status ? { status } : {}), limit: 20, cursor }, controller.signal)
      .then(page => { if (active) { setItems(page.items); setNextCursor(page.next_cursor); } })
      .catch(failure => { if (active && !controller.signal.aborted) setError(failureMessage(failure)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [api, scope, status, cursor, refresh]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setDetail(null);
    setDetailError(null);
    if (selectedId) {
      api.get(selectedId, controller.signal)
        .then(value => { if (active) setDetail(value); })
        .catch(failure => { if (active && !controller.signal.aborted) setDetailError(failureMessage(failure)); });
    }
    return () => { active = false; controller.abort(); };
  }, [api, selectedId, refresh]);

  function resetPage() { setCursors([undefined]); setRefresh(value => value + 1); }

  async function mutate(action: (signal: AbortSignal) => Promise<Listing>): Promise<void> {
    if (mutationLock.current) return;
    mutationLock.current = true;
    const controller = new AbortController();
    mutationController.current = controller;
    setBusy(true);
    setError(null);
    try {
      const result = await action(controller.signal);
      if (!controller.signal.aborted) {
        setEditor(null);
        setSelectedId(result.id);
        if (editor?.kind === "create") { setScope("mine"); setStatus(""); }
        resetPage();
      }
    } finally {
      mutationLock.current = false;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  function actions(item: Listing) {
    if (session.role !== "WORKER" || scope !== "mine") return null;
    return <div className="listings-actions">
      <button type="button" disabled={busy} onClick={() => setEditor({ kind: "edit", listing: item })}>Chỉnh sửa</button>
      <button type="button" disabled={busy} onClick={() => {
        void mutate(signal => item.status === "ACTIVE" ? api.pause(item.id, signal) : api.resume(item.id, signal))
          .catch(failure => { if (!(failure instanceof Error && failure.name === "AbortError")) setError(failureMessage(failure)); });
      }}>{item.status === "ACTIVE" ? "Tạm dừng" : "Khôi phục"}</button>
    </div>;
  }

  async function save(input: ListingInput | Partial<ListingInput>) {
    if (!editor) return;
    await mutate(signal => editor.kind === "create"
      ? api.create(input as ListingInput, signal)
      : api.patch(editor.listing.id, input, signal));
  }

  return (
    <main className="listings-shell">
      <header className="listings-header">
        <div><p className="listings-eyebrow">GPU Resource Marketplace</p><h1>GPU Listings</h1><p>Tài nguyên GPU mô phỏng, được quản lý theo quyền sở hữu.</p></div>
        {session.role === "WORKER" && <button type="button" disabled={busy} onClick={() => setEditor({ kind: "create" })}>Tạo Listing</button>}
      </header>
      <section className="listings-toolbar" aria-label="Bộ lọc Listings">
        <label>Phạm vi<select value={scope} disabled={busy} onChange={event => { setScope(event.target.value as ListingScope); setStatus(""); setSelectedId(null); setEditor(null); setCursors([undefined]); }}>
          <option value="marketplace">Marketplace</option>
          {session.role === "WORKER" && <option value="mine">Listings của tôi</option>}
          {session.role === "ADMIN" && <option value="all">Tất cả Listings</option>}
        </select></label>
        {scope !== "marketplace" && <label>Trạng thái<select value={status} disabled={busy} onChange={event => { setStatus(event.target.value as ListingStatus | ""); setCursors([undefined]); }}>
          <option value="">Tất cả trạng thái</option><option value="ACTIVE">ACTIVE</option><option value="PAUSED">PAUSED</option>
        </select></label>}
        <button type="button" disabled={loading || busy} onClick={resetPage}>Tải lại</button>
      </section>
      {editor && <ListingForm key={editor.kind === "edit" ? editor.listing.id : "new"} listing={editor.kind === "edit" ? editor.listing : undefined} busy={busy} onSubmit={save} onCancel={() => setEditor(null)} />}
      {error && <p role="alert" className="listings-error">{error}</p>}
      {loading && <p role="status">Đang tải Listings…</p>}
      {!loading && !error && items.length === 0 && <p>Chưa có Listing phù hợp.</p>}
      <section className="listings-grid" aria-label="Danh sách GPU" aria-busy={loading}>
        {items.map(item => <article className="listings-card" key={item.id}>
          <div className="listings-card-heading"><h2>{item.gpu_model}</h2><span className={`listings-badge listings-${item.status.toLowerCase()}`}>{item.status}</span></div>
          <p>{item.worker.display_name}</p>
          <dl><dt>VRAM</dt><dd>{item.vram_gb} GB</dd><dt>GPU khả dụng</dt><dd>{item.available_gpu_count} / {item.total_gpu_count}</dd><dt>Giá mô phỏng/giờ</dt><dd>{item.mock_price_per_hour ?? "Chưa đặt"}</dd></dl>
          <button type="button" onClick={() => setSelectedId(item.id)}>Xem chi tiết</button>
          {actions(item)}
        </article>)}
      </section>
      <nav className="listings-actions" aria-label="Phân trang">
        <button type="button" disabled={cursors.length === 1 || loading || busy} onClick={() => setCursors(values => values.slice(0, -1))}>Trang trước</button>
        <span>Trang {cursors.length}</span>
        <button type="button" disabled={!nextCursor || loading || busy} onClick={() => { if (nextCursor) setCursors(values => [...values, nextCursor]); }}>Trang sau</button>
      </nav>
      {selectedId && <section className="listings-panel" aria-labelledby="listing-detail-title">
        <div className="listings-card-heading"><h2 id="listing-detail-title">Chi tiết Listing</h2><button type="button" onClick={() => setSelectedId(null)}>Đóng chi tiết</button></div>
        {detailError && <p role="alert" className="listings-error">{detailError}</p>}
        {!detail && !detailError && <p role="status">Đang tải chi tiết…</p>}
        {detail && <>
          <h3>{detail.gpu_model}</h3><p>{detail.worker.display_name} · {detail.status}</p>
          <dl><dt>VRAM</dt><dd>{detail.vram_gb} GB</dd><dt>Tổng GPU</dt><dd>{detail.total_gpu_count}</dd><dt>Đã cấp phát</dt><dd>{detail.allocated_gpu_count}</dd><dt>Khả dụng</dt><dd>{detail.available_gpu_count}</dd><dt>Giá mô phỏng/giờ</dt><dd>{detail.mock_price_per_hour ?? "Chưa đặt"}</dd><dt>Reputation (tỷ lệ thành công)</dt><dd>{detail.worker.reputation.success_rate ?? "N/A"}</dd></dl>
          <p>{detail.accepting_jobs ? "Listing đang nhận yêu cầu mới." : "Listing đã tạm dừng nhận yêu cầu mới."} Khả dụng là ảnh chụp hiện tại, không phải giữ chỗ GPU.</p>
          <p className="listings-muted">Giá chỉ dùng cho mô phỏng.</p>
        </>}
      </section>}
    </main>
  );
}
