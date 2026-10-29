import { useRef, useState } from "react";
import type { FormEvent } from "react";

import type { Listing, ListingInput } from "../../api/listings";

interface Props {
  listing?: Listing;
  busy: boolean;
  onSubmit: (input: ListingInput | Partial<ListingInput>) => Promise<void>;
  onCancel: () => void;
}

function positiveInteger(raw: string): number {
  if (!/^[0-9]+$/.test(raw) || !Number.isSafeInteger(Number(raw)) || Number(raw) < 1 || Number(raw) > 2147483647) {
    throw new Error("VRAM và tổng GPU phải là số nguyên dương, tối đa 2147483647.");
  }
  return Number(raw);
}

export function ListingForm({ listing, busy, onSubmit, onCancel }: Props) {
  const [model, setModel] = useState(listing?.gpu_model ?? "");
  const [vram, setVram] = useState(String(listing?.vram_gb ?? ""));
  const [total, setTotal] = useState(String(listing?.total_gpu_count ?? ""));
  const [price, setPrice] = useState(listing?.mock_price_per_hour ?? "");
  const [error, setError] = useState<string | null>(null);
  const submitting = useRef(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || submitting.current) return;
    submitting.current = true;
    setError(null);
    try {
      const name = model.trim();
      if (!name || name.length > 160) throw new Error("Model GPU cần từ 1 đến 160 ký tự.");
      const amount = price.trim();
      if (amount && (!/^[0-9]+\.[0-9]{2}$/.test(amount) || amount.split(".")[0].replace(/^0+/, "").length > 10)) {
        throw new Error("Giá cần đúng hai số thập phân, từ 0.00 đến 9999999999.99.");
      }
      const values: ListingInput = { gpu_model: name, vram_gb: positiveInteger(vram), total_gpu_count: positiveInteger(total), mock_price_per_hour: amount || null };
      const input = listing ? Object.fromEntries(Object.entries(values).filter(([key, value]) => listing[key as keyof ListingInput] !== value)) : values;
      if (!Object.keys(input).length) throw new Error("Chưa có thông tin nào thay đổi.");
      await onSubmit(input);
    } catch (failure) {
      if (!(failure instanceof Error && failure.name === "AbortError")) setError(failure instanceof Error ? failure.message : "Không thể lưu Listing.");
    } finally {
      submitting.current = false;
    }
  }

  return (
    <section className="listings-panel" aria-labelledby="listing-form-title">
      <h2 id="listing-form-title">{listing ? "Chỉnh sửa Listing" : "Tạo Listing"}</h2>
      <form onSubmit={submit} noValidate>
        <fieldset disabled={busy} className="listings-fields">
          <label>Model GPU<input value={model} onChange={event => setModel(event.target.value)} maxLength={160} required /></label>
          <label>VRAM (GB)<input inputMode="numeric" value={vram} onChange={event => setVram(event.target.value)} required /></label>
          <label>Tổng GPU<input inputMode="numeric" value={total} onChange={event => setTotal(event.target.value)} required /></label>
          <label>Giá mô phỏng mỗi giờ (tùy chọn)<input inputMode="decimal" placeholder="12.50" value={price} onChange={event => setPrice(event.target.value)} /></label>
        </fieldset>
        {error && <p role="alert" className="listings-error">{error}</p>}
        <div className="listings-actions">
          <button type="submit" disabled={busy}>{busy ? "Đang lưu…" : "Lưu Listing"}</button>
          <button type="button" disabled={busy} onClick={onCancel}>Hủy</button>
        </div>
      </form>
    </section>
  );
}
