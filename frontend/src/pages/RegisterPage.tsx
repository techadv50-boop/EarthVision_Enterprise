import { useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';

export function RegisterPage() {
  const { user, register, loading, error, clearError } = useAuthStore();
  const navigate = useNavigate();
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
      navigate('/app');
    } catch {
      // stored
    }
  };

  return (
    <div className="flex min-h-full items-center justify-center overflow-auto p-6">
      <form onSubmit={onSubmit} className="ev-panel w-full max-w-md animate-fade-up p-6">
        <h1 className="font-display text-2xl font-semibold">Create account</h1>
        <p className="mb-5 text-xs text-earth-400">Join EarthVision Enterprise</p>
        {(
          [
            ['full_name', 'Full name', 'text'],
            ['email', 'Email', 'email'],
            ['organization', 'Organization', 'text'],
            ['password', 'Password', 'password'],
          ] as const
        ).map(([key, label, type]) => (
          <div key={key} className="mb-3">
            <label className="ev-label">{label}</label>
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
          <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            {error}
          </div>
        )}
        <button type="submit" className="ev-btn-primary w-full" disabled={loading}>
          {loading ? 'Creating…' : 'Create account'}
        </button>
        <p className="mt-4 text-center text-xs text-earth-400">
          Already have an account?{' '}
          <Link to="/login" className="text-orbit-400 hover:underline">
            Sign in
          </Link>
        </p>
      </form>
    </div>
  );
}
