import { useId, useState } from "react";
import type { FormEvent } from "react";

import { AuthApiError } from "../../api/auth";
import type { SessionStore, SignedOutReason } from "../../api/session";

const notices: Record<SignedOutReason, string> = {
  "signed-out": "Bạn đã đăng xuất.",
  expired: "Phiên đăng nhập đã hết hạn sau 15 phút. Vui lòng đăng nhập lại.",
  unauthorized: "Phiên đăng nhập không còn hợp lệ. Vui lòng đăng nhập lại.",
};

// Same edge set the API trims (ASCII SP/HT/LF/CR, DEC-P1-03); other Unicode spaces are kept.
const blank = /^[ \t\n\r]*$/;

interface Props {
  store: SessionStore;
  reason?: SignedOutReason;
}

export function LoginForm({ store, reason }: Props) {
  const id = useId();
  const [loginName, setLoginName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (blank.test(loginName) || password === "") {
      setError("Vui lòng nhập tên đăng nhập và mật khẩu.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await store.signIn(loginName, password);
    } catch (failure) {
      if (failure instanceof DOMException && failure.name === "AbortError") return;
      // AuthApiError messages are fixed texts; anything else gets a generic one.
      setError(failure instanceof AuthApiError ? failure.message : "Không thể đăng nhập lúc này.");
    } finally {
      setPassword(""); // do not keep the password in component state after an attempt
      setBusy(false);
    }
  }

  return (
    <form className="auth-form" onSubmit={submit} noValidate aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>Đăng nhập</h2>
      {reason && !error && <p className="auth-notice" role="status">{notices[reason]}</p>}
      <label htmlFor={`${id}-login`}>Tên đăng nhập</label>
      <input
        id={`${id}-login`} name="login_name" autoComplete="username" spellCheck={false} autoCapitalize="none"
        value={loginName} onChange={(event) => setLoginName(event.target.value)} disabled={busy}
      />
      <label htmlFor={`${id}-password`}>Mật khẩu</label>
      <input
        id={`${id}-password`} name="password" type="password" autoComplete="current-password"
        value={password} onChange={(event) => setPassword(event.target.value)} disabled={busy}
      />
      {error && <p className="auth-error" role="alert">{error}</p>}
      <button type="submit" disabled={busy}>{busy ? "Đang đăng nhập…" : "Đăng nhập"}</button>
    </form>
  );
}
