import { useState } from "react";

import type { AuthUser, UserRole } from "../../api/auth";
import type { SessionStore } from "../../api/session";

const roleLabels: Record<UserRole, string> = {
  CLIENT: "Client — thuê GPU",
  WORKER: "Worker — cho thuê GPU",
  ADMIN: "Admin — chỉ xem",
};

interface Props {
  store: SessionStore;
  user: AuthUser;
}

export function AccountPanel({ store, user }: Props) {
  const [busy, setBusy] = useState(false);

  async function signOut() {
    setBusy(true);
    await store.signOut();
  }

  return (
    <section className="auth-account" aria-label="Tài khoản hiện tại">
      <dl>
        <dt>Đăng nhập với</dt>
        <dd>{user.loginName}</dd>
        <dt>Vai trò</dt>
        <dd>{roleLabels[user.role]}</dd>
      </dl>
      <button type="button" onClick={signOut} disabled={busy}>Đăng xuất</button>
      {/* Approved limitation that the UI must disclose (API Contract section 4.4). */}
      <p className="auth-hint">
        Đăng xuất xóa phiên khỏi trình duyệt này. Máy chủ không thu hồi mã đã cấp: nếu mã bị sao chép,
        nó vẫn dùng được tới khi hết hạn (tối đa 15 phút). Tải lại trang cũng sẽ đăng xuất.
      </p>
    </section>
  );
}
