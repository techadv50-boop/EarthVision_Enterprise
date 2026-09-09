import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { AuthUser } from "../lib/auth";

export default function AdminPanel() {
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  async function load() {
    setError("");
    try {
      setUsers(await api.adminUsers());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load users");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function act(id: string, action: "allow" | "decline" | "restrict" | "renew") {
    setBusyId(id);
    setError("");
    try {
      await api.adminAction(id, action);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusyId(null);
    }
  }

  const pending = users.filter((u) => u.status === "pending");

  return (
    <section className="panel">
      <h2>Admin — account requests</h2>
      <p className="empty">
        New signups appear here. Allow starts a 1-month subscription. Decline or
        Restrict blocks access. Renew extends another month.
      </p>
      {error && <p className="status error">{error}</p>}

      {pending.length > 0 && (
        <div className="admin-alert">
          {pending.length} account request{pending.length > 1 ? "s" : ""} waiting
        </div>
      )}

      <div className="admin-list">
        {users.map((user) => (
          <div key={user.id} className="admin-row">
            <div>
              <strong>{user.name}</strong>
              <div className="sample-meta">
                {user.email} · {user.role} · status: {user.status}
                {user.subscription_ends_at
                  ? ` · ends ${new Date(user.subscription_ends_at).toLocaleDateString()}`
                  : ""}
                {user.days_remaining !== null && user.days_remaining !== undefined
                  ? ` · ${user.days_remaining}d left`
                  : ""}
              </div>
            </div>
            {user.role !== "admin" && (
              <div className="row">
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={busyId === user.id}
                  onClick={() => act(user.id, "allow")}
                >
                  Allow
                </button>
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={busyId === user.id}
                  onClick={() => act(user.id, "renew")}
                >
                  Renew month
                </button>
                <button
                  type="button"
                  className="btn btn-ghost"
                  disabled={busyId === user.id}
                  onClick={() => act(user.id, "restrict")}
                >
                  Restrict
                </button>
                <button
                  type="button"
                  className="btn btn-danger"
                  disabled={busyId === user.id}
                  onClick={() => act(user.id, "decline")}
                >
                  Decline
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
