import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { BookOpen, Loader2 } from 'lucide-react';
import { isCitationAdmin, useAuthStore } from '@/store/authStore';
import { authApi } from '@/services/api';

export default function LoginPage() {
  const [username, setUsername] = useState('citation@xdgen.com');
  const [password, setPassword] = useState('pak123');
  const [masterPassword, setMasterPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [showReset, setShowReset] = useState(false);
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const { login, isLoading } = useAuthStore();
  const [resetting, setResetting] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setInfo('');
    try {
      await login(username, password);
      const signedIn = useAuthStore.getState().user;
      navigate(isCitationAdmin(signedIn) ? '/' : '/manuscripts');
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined;
      setError(
        typeof detail === 'string'
          ? detail
          : 'Invalid credentials. Use citation@xdgen.com / pak123',
      );
    }
  };

  const handleReset = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setInfo('');
    setResetting(true);
    try {
      await authApi.resetPassword(username, masterPassword, newPassword);
      setPassword(newPassword);
      setMasterPassword('');
      setNewPassword('');
      setShowReset(false);
      setInfo('Password reset. Sign in with the new password.');
    } catch {
      setError('Reset failed. Check the email and master reset password.');
    } finally {
      setResetting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-earth-900/20 via-gray-950 to-gray-950" />

      <div className="relative panel p-8 w-full max-w-md">
        <div className="text-center mb-8">
          <BookOpen className="w-16 h-16 text-earth-400 mx-auto mb-4" />
          <h1 className="text-2xl font-bold">Citation Assistant</h1>
          <p className="text-gray-500 mt-2">citation.xdgen.com · IJIST archive</p>
        </div>

        {!showReset ? (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-sm text-gray-400 mb-1 block">Email</label>
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
              <label className="text-sm text-gray-400 mb-1 block">Password</label>
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
            {info && <p className="text-earth-400 text-sm">{info}</p>}

            <button
              type="submit"
              disabled={isLoading}
              className="btn-primary w-full flex items-center justify-center gap-2"
            >
              {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Sign In'}
            </button>
            <button
              type="button"
              className="w-full text-sm text-gray-500 hover:text-earth-400"
              onClick={() => {
                setShowReset(true);
                setError('');
                setInfo('');
              }}
            >
              Forgot password? Use master reset
            </button>
            <p className="text-center text-sm text-gray-500">
              Need an account?{' '}
              <button
                type="button"
                className="text-earth-400 hover:underline"
                onClick={() => navigate('/register')}
              >
                Create one
              </button>
            </p>
          </form>
        ) : (
          <form onSubmit={handleReset} className="space-y-4">
            <p className="text-sm text-gray-400">
              Enter the account email, the master reset password <span className="text-gray-200">NTZHSS</span>, and a
              new login password.
            </p>
            <div>
              <label className="text-sm text-gray-400 mb-1 block">Email</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="input-field"
                required
              />
            </div>
            <div>
              <label className="text-sm text-gray-400 mb-1 block">Master reset password</label>
              <input
                type="password"
                value={masterPassword}
                onChange={(e) => setMasterPassword(e.target.value)}
                className="input-field"
                required
              />
            </div>
            <div>
              <label className="text-sm text-gray-400 mb-1 block">New password</label>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="input-field"
                minLength={6}
                required
              />
            </div>
            {error && <p className="text-red-400 text-sm">{error}</p>}
            <button
              type="submit"
              disabled={resetting}
              className="btn-primary w-full flex items-center justify-center gap-2"
            >
              {resetting ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Reset password'}
            </button>
            <button
              type="button"
              className="w-full text-sm text-gray-500 hover:text-earth-400"
              onClick={() => {
                setShowReset(false);
                setError('');
              }}
            >
              Back to sign in
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
