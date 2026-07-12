import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Globe, Loader2 } from 'lucide-react';
import { useAuthStore } from '@/store/authStore';

export default function LoginPage() {
  const [username, setUsername] = useState('demo');
  const [password, setPassword] = useState('Demo@123456');
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
      setError('Invalid credentials. Try demo / Demo@123456');
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-earth-900/20 via-gray-950 to-gray-950" />

      <div className="relative panel p-8 w-full max-w-md">
        <div className="text-center mb-8">
          <Globe className="w-16 h-16 text-earth-400 mx-auto mb-4" />
          <h1 className="text-2xl font-bold">EarthVision Enterprise</h1>
          <p className="text-gray-500 mt-2">Earth Observation Platform</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-sm text-gray-400 mb-1 block">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="input-field"
              required
            />
          </div>
          <div>
            <label className="text-sm text-gray-400 mb-1 block">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input-field"
              required
            />
          </div>

          {error && <p className="text-red-400 text-sm">{error}</p>}

          <button type="submit" disabled={isLoading} className="btn-primary w-full flex items-center justify-center gap-2">
            {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Sign In'}
          </button>
        </form>

        <div className="mt-6 text-center text-sm text-gray-500">
          <p>
            No account?{' '}
            <Link to="/register" className="text-earth-400 hover:underline">
              Create one
            </Link>
          </p>
        </div>

        <div className="mt-4 text-center text-xs text-gray-600">
          <p>Demo: demo / Demo@123456</p>
          <p className="mt-1">Admin: admin / Admin@123456</p>
        </div>
      </div>
    </div>
  );
}
