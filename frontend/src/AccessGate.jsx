import { useEffect, useState } from "react";
import { checkAccess, setAccessKey, clearAccessKey } from "./api";

export default function AccessGate({ children }) {
  const [status, setStatus] = useState("checking"); // checking | locked | unlocked
  const [keyInput, setKeyInput] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;

    // On load, ask the backend whether the stored key is valid (or whether
    // auth is even enabled). 401 -> show the lock screen; anything else -> in.
    checkAccess()
      .then(() => !cancelled && setStatus("unlocked"))
      .catch((err) => {
        if (cancelled) return;
        setStatus(err?.response?.status === 401 ? "locked" : "unlocked");
      });

    // The axios interceptor fires this if a key is rejected mid-session.
    function onUnauthorized() {
      clearAccessKey();
      setStatus("locked");
    }
    window.addEventListener("app-unauthorized", onUnauthorized);
    return () => {
      cancelled = true;
      window.removeEventListener("app-unauthorized", onUnauthorized);
    };
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    setAccessKey(keyInput.trim());
    try {
      await checkAccess();
      setStatus("unlocked");
    } catch (err) {
      clearAccessKey();
      setError(
        err?.response?.status === 401
          ? "Incorrect access key."
          : "Could not reach the server. Try again."
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (status === "checking") {
    return (
      <main className="page">
        <p className="subtitle">Loading…</p>
      </main>
    );
  }

  if (status === "unlocked") return children;

  return (
    <main className="page">
      <section className="card lockScreen">
        <p className="eyebrow">Protected</p>
        <h1>Enter Access Key</h1>
        <p className="subtitle">This tool is private. Enter the shared access key to continue.</p>
        <form onSubmit={handleSubmit} className="form">
          <label>
            Access Key
            <input
              type="password"
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              placeholder="••••••••••••"
              autoFocus
              required
            />
          </label>
          <button disabled={submitting} type="submit">
            {submitting ? "Checking…" : "Unlock"}
          </button>
        </form>
        {error && <div className="error">{error}</div>}
      </section>
    </main>
  );
}
