import { useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';

export function LoginPage() {
  const { user, login, loading, error, clearError } = useAuthStore();
  const navigate = useNavigate();
  const [email, setEmail] = useState('admin@earthvision.io');
  const [password, setPassword] = useState('EarthVision@Admin2024!');

  if (user) return <Navigate to="/app" replace />;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    clearError();
    try {
      await login(email, password);
      navigate('/app');
    } catch {
      // store holds error
    }
  };

  return (
    <div className="flex min-h-full items-center justify-center bg-[var(--bg)] p-4">
      <form onSubmit={onSubmit} className="ev-card w-full max-w-sm p-6">
        <h1 className="font-display text-xl font-semibold">SAT EYE</h1>
        <p className="mb-5 text-sm text-[var(--muted)]">Eye In Sky — sign in to explore satellite imagery</p>

        <label className="mb-1 block text-xs font-medium text-[var(--muted)]">Email</label>
        <input
          className="ev-input mb-3"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoComplete="username"
        />

        <label className="mb-1 block text-xs font-medium text-[var(--muted)]">Password</label>
        <input
          className="ev-input mb-4"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="current-password"
        />

        {error && (
          <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </div>
        )}

        <button type="submit" className="ev-btn-primary w-full" disabled={loading}>
          {loading ? 'Signing in…' : 'Sign in'}
        </button>

        <p className="mt-4 text-center text-xs text-[var(--muted)]">
          No account?{' '}
          <Link to="/register" className="text-[var(--accent)] hover:underline">
            Create one
          </Link>
        </p>
      </form>
    </div>
  );
}
