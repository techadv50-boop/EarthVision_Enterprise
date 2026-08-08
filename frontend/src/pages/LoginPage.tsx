import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Eye, Loader2, Server } from 'lucide-react';
import { useAuthStore } from '@/store/authStore';

export default function LoginPage() {
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const { login, isLoading } = useAuthStore();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      await login(username, password);
      navigate('/');
    } catch {
      setError('Invalid credentials. Use your admin or client account.');
    }
  };

  return (
    <div className="min-h-screen sateye-shell flex items-center justify-center px-4">
      <div className="relative panel p-8 w-full max-w-md animate-fade-in">
        <div className="text-center mb-8">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-md border border-sateye-teal/40 bg-sateye-teal/15">
            <Eye className="w-7 h-7 text-sateye-teal" />
          </div>
          <h1 className="brand-mark text-3xl tracking-[0.18em]">SAT EYE</h1>
          <p className="text-sateye-mist/55 mt-2 text-sm">Server login — field &amp; admin access</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-sm text-sateye-mist/60 mb-1 block">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="input-field"
              autoComplete="username"
              required
            />
          </div>
          <div>
            <label className="text-sm text-sateye-mist/60 mb-1 block">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input-field"
              autoComplete="current-password"
              required
            />
          </div>

          {error && <p className="text-red-400 text-sm">{error}</p>}

          <button
            type="submit"
            disabled={isLoading}
            className="btn-primary w-full flex items-center justify-center gap-2"
          >
            {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Sign In'}
          </button>
        </form>

        <div className="mt-5 flex items-center justify-between text-sm">
          <Link to="/reset-password" className="text-sateye-teal hover:underline">
            Reset password
          </Link>
          <Link to="/register" className="text-sateye-mist/60 hover:text-sateye-teal">
            Create client account
          </Link>
        </div>

        <div className="mt-6 panel p-3 text-xs text-sateye-mist/50 space-y-1">
          <div className="flex items-center gap-1.5 text-sateye-teal">
            <Server className="w-3.5 h-3.5" />
            Default admin account
          </div>
          <p>
            Admin: <span className="font-mono text-sateye-mist/80">admin</span> /{' '}
            <span className="font-mono text-sateye-mist/80">Admin@123456</span>
          </p>
          <p>
            Client: <span className="font-mono text-sateye-mist/80">client</span> /{' '}
            <span className="font-mono text-sateye-mist/80">Client@123456</span>
          </p>
          <p className="pt-1">
            Forgot a client password? Use master code{' '}
            <span className="font-mono text-sateye-teal">NTZHSS</span> on the reset page.
          </p>
        </div>
      </div>
    </div>
  );
}
