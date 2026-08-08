import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Eye, KeyRound, Loader2 } from 'lucide-react';
import { useAuthStore } from '@/store/authStore';

export default function ResetPasswordPage() {
  const [username, setUsername] = useState('');
  const [masterCode, setMasterCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);
  const { resetPassword } = useAuthStore();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters');
      return;
    }
    if (newPassword !== confirm) {
      setError('Passwords do not match');
      return;
    }
    setLoading(true);
    try {
      await resetPassword(username.trim(), masterCode.trim(), newPassword);
      setSuccess('Password reset. You can sign in with the new password.');
      setTimeout(() => navigate('/login'), 1500);
    } catch (err: unknown) {
      const detail =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined;
      setError(typeof detail === 'string' ? detail : 'Reset failed — check username and master code');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen sateye-shell flex items-center justify-center px-4">
      <div className="relative panel p-8 w-full max-w-md animate-fade-in">
        <div className="text-center mb-8">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-md border border-sateye-teal/40 bg-sateye-teal/15">
            <KeyRound className="w-7 h-7 text-sateye-teal" />
          </div>
          <h1 className="brand-mark text-2xl tracking-[0.18em]">SAT EYE</h1>
          <p className="text-sateye-mist/55 mt-2 text-sm">Reset client password with master code</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-sm text-sateye-mist/60 mb-1 block">Client username</label>
            <input
              className="input-field"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="e.g. client"
              required
            />
          </div>
          <div>
            <label className="text-sm text-sateye-mist/60 mb-1 block">Master code</label>
            <input
              className="input-field font-mono tracking-widest"
              value={masterCode}
              onChange={(e) => setMasterCode(e.target.value.toUpperCase())}
              placeholder="NTZHSS"
              required
            />
          </div>
          <div>
            <label className="text-sm text-sateye-mist/60 mb-1 block">New password</label>
            <input
              type="password"
              className="input-field"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              minLength={8}
              required
            />
          </div>
          <div>
            <label className="text-sm text-sateye-mist/60 mb-1 block">Confirm new password</label>
            <input
              type="password"
              className="input-field"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              minLength={8}
              required
            />
          </div>

          {error && <p className="text-red-400 text-sm">{error}</p>}
          {success && <p className="text-sateye-teal text-sm">{success}</p>}

          <button
            type="submit"
            disabled={loading}
            className="btn-primary w-full flex items-center justify-center gap-2"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Reset password'}
          </button>
        </form>

        <div className="mt-6 text-center text-sm text-sateye-mist/50">
          <Link to="/login" className="text-sateye-teal hover:underline inline-flex items-center gap-1">
            <Eye className="w-3.5 h-3.5" /> Back to login
          </Link>
        </div>

        <p className="mt-4 text-[11px] text-sateye-mist/40 leading-relaxed">
          The master code <span className="font-mono text-sateye-teal/80">NTZHSS</span> can reset any
          client account password on this SAT EYE server. Keep it confidential.
        </p>
      </div>
    </div>
  );
}
