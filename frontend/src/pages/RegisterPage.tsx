import { useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';

export function RegisterPage() {
  const { user, register, loading, error, clearError, registrationPending } =
    useAuthStore();
  const [form, setForm] = useState({
    email: '',
    password: '',
    full_name: '',
    organization: '',
  });

  if (user) return <Navigate to="/app" replace />;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    clearError();
    try {
      await register({
        email: form.email,
        password: form.password,
        full_name: form.full_name,
        organization: form.organization || undefined,
      });
    } catch {
      // stored
    }
  };

  if (registrationPending) {
    return (
      <div className="flex min-h-full items-center justify-center bg-[var(--bg)] p-4">
        <div className="ev-card w-full max-w-sm p-6">
          <h1 className="font-display text-xl font-semibold">Request received</h1>
          <p className="mt-3 text-sm text-[var(--muted)]">
            Your account was created and is <strong>pending administrator approval</strong>.
            An admin will approve, decline, or restrict your services (tools and satellites)
            before you can sign in.
          </p>
          <Link to="/login" className="ev-btn-primary mt-5 inline-flex w-full justify-center">
            Back to sign in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-[var(--bg)] p-4">
      <form onSubmit={onSubmit} className="ev-card w-full max-w-sm p-6">
        <h1 className="font-display text-xl font-semibold">Request access</h1>
        <p className="mb-5 text-sm text-[var(--muted)]">
          Create a client account. Final access is granted by an administrator
          (approve / decline / restrict services).
        </p>
        {(
          [
            ['full_name', 'Full name', 'text'],
            ['email', 'Email', 'email'],
            ['organization', 'Organization', 'text'],
            ['password', 'Password', 'password'],
          ] as const
        ).map(([key, label, type]) => (
          <div key={key} className="mb-3">
            <label className="mb-1 block text-xs font-medium text-[var(--muted)]">{label}</label>
            <input
              className="ev-input"
              type={type}
              required={key !== 'organization'}
              minLength={key === 'password' ? 8 : undefined}
              value={form[key]}
              onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
            />
          </div>
        ))}
        {error && (
          <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </div>
        )}
        <button type="submit" className="ev-btn-primary w-full" disabled={loading}>
          {loading ? 'Submitting…' : 'Submit for approval'}
        </button>
        <p className="mt-4 text-center text-xs text-[var(--muted)]">
          Already approved?{' '}
          <Link to="/login" className="text-[var(--accent)] hover:underline">
            Sign in
          </Link>
        </p>
      </form>
    </div>
  );
}
