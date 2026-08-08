import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Eye, Loader2 } from 'lucide-react';
import { authApi } from '@/services/api';
import { useAuthStore } from '@/store/authStore';

export default function RegisterPage() {
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuthStore();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await authApi.register({
        email,
        username,
        password,
        full_name: fullName || undefined,
      });
      await login(username, password);
      navigate('/');
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined;
      setError(typeof detail === 'string' ? detail : 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen sateye-shell flex items-center justify-center px-4">
      <div className="relative panel p-8 w-full max-w-md animate-fade-in">
        <div className="text-center mb-8">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-md border border-sateye-teal/40 bg-sateye-teal/15">
            <Eye className="w-7 h-7 text-sateye-teal" />
          </div>
          <h1 className="brand-mark text-2xl tracking-[0.18em]">SAT EYE</h1>
          <p className="text-sateye-mist/55 mt-2 text-sm">Create a field client account</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-sm text-sateye-mist/60 mb-1 block">Full name</label>
            <input
              className="input-field"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </div>
          <div>
            <label className="text-sm text-sateye-mist/60 mb-1 block">Email</label>
            <input
              type="email"
              className="input-field"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="text-sm text-sateye-mist/60 mb-1 block">Username</label>
            <input
              className="input-field"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              minLength={3}
              required
            />
          </div>
          <div>
            <label className="text-sm text-sateye-mist/60 mb-1 block">Password</label>
            <input
              type="password"
              className="input-field"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              required
            />
          </div>

          {error && <p className="text-red-400 text-sm">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="btn-primary w-full flex items-center justify-center gap-2"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Create account'}
          </button>
        </form>

        <div className="mt-6 text-center text-sm text-sateye-mist/50">
          Already have an account?{' '}
          <Link to="/login" className="text-sateye-teal hover:underline">
            Sign in
          </Link>
        </div>
      </div>
    </div>
  );
}
