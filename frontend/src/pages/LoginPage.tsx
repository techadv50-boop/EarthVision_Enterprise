import { useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { Globe2, Lock, Mail } from 'lucide-react';
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
      // error in store
    }
  };

  return (
    <div className="relative flex min-h-full items-center justify-center overflow-auto p-6">
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(ellipse 70% 50% at 50% 0%, rgba(59,163,199,0.25), transparent 55%), radial-gradient(circle at 80% 80%, rgba(196,165,116,0.12), transparent 40%)',
        }}
      />
      <div className="relative grid w-full max-w-5xl gap-8 lg:grid-cols-2 lg:items-center">
        <div className="animate-fade-up text-center lg:text-left">
          <div className="mb-4 inline-flex items-center gap-3">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-orbit-500 to-earth-600 shadow-lg animate-pulse-ring">
              <Globe2 className="h-7 w-7 text-white" />
            </div>
            <div>
              <h1 className="font-display text-3xl font-bold tracking-tight text-earth-50 md:text-4xl">
                EarthVision
              </h1>
              <p className="text-xs uppercase tracking-[0.25em] text-orbit-400">Enterprise</p>
            </div>
          </div>
          <p className="mx-auto max-w-md text-sm leading-relaxed text-earth-300 lg:mx-0">
            Commercial Earth observation — globe visualization, satellite catalog search,
            spectral analytics, and geospatial AI in one integrated platform.
          </p>
        </div>

        <form
          onSubmit={onSubmit}
          className="ev-panel animate-fade-up mx-auto w-full max-w-md p-6"
          style={{ animationDelay: '100ms' }}
        >
          <h2 className="mb-1 font-display text-xl font-semibold">Sign in</h2>
          <p className="mb-5 text-xs text-earth-400">Access your EarthVision workspace</p>

          <label className="ev-label">Email</label>
          <div className="relative mb-3">
            <Mail className="absolute left-3 top-2.5 h-4 w-4 text-earth-500" />
            <input
              className="ev-input pl-9"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="username"
            />
          </div>

          <label className="ev-label">Password</label>
          <div className="relative mb-4">
            <Lock className="absolute left-3 top-2.5 h-4 w-4 text-earth-500" />
            <input
              className="ev-input pl-9"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </div>

          {error && (
            <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
              {error}
            </div>
          )}

          <button type="submit" className="ev-btn-primary w-full" disabled={loading}>
            {loading ? 'Signing in…' : 'Sign in'}
          </button>

          <p className="mt-4 text-center text-xs text-earth-400">
            No account?{' '}
            <Link to="/register" className="text-orbit-400 hover:underline">
              Create one
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
