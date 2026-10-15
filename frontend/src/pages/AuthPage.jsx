import { useState } from "react";
import { api } from "../api.js";

export default function AuthPage({ onLogin }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const registering = mode === "register";

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (registering && password !== confirm) return setError("Passwords don't match.");
    setBusy(true);
    try {
      await (registering ? api.register : api.login)(username, password);
      await onLogin();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={submit}>
        <div className="brand brand-lg">
          <span className="brand-mark" />
          KJP Paper Trader
        </div>
        <h1>{registering ? "Create your account" : "Log in"}</h1>
        <p className="muted">
          {registering
            ? "You'll start with $100,000 in paper money to trade real stocks and ETFs."
            : "Welcome back. Your portfolio is right where you left it."}
        </p>
        <label>
          Username
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" required />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={registering ? "new-password" : "current-password"}
            required
          />
        </label>
        {registering && (
          <label>
            Confirm password
            <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required />
          </label>
        )}
        {error && <div className="error">{error}</div>}
        <button className="btn btn-primary btn-block" disabled={busy}>
          {busy ? "…" : registering ? "Create account" : "Log in"}
        </button>
        <button
          type="button"
          className="link"
          onClick={() => {
            setMode(registering ? "login" : "register");
            setError("");
          }}
        >
          {registering ? "Already have an account? Log in" : "New here? Create an account"}
        </button>
      </form>
    </div>
  );
}
