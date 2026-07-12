import { Globe, LogOut } from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { useNavigate } from 'react-router-dom';

export default function Header() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <header className="absolute top-0 left-0 right-0 z-30 flex items-center justify-between px-4 py-2 bg-gray-950/80 backdrop-blur-md border-b border-gray-800">
      <div className="flex items-center gap-3">
        <Globe className="w-6 h-6 text-earth-400" />
        <div>
          <h1 className="text-sm font-bold tracking-wide">EarthVision Enterprise</h1>
          <p className="text-xs text-gray-500">Earth Observation Platform</p>
        </div>
      </div>
      <div className="flex items-center gap-4">
        {user && (
          <span className="text-sm text-gray-400">
            {user.full_name || user.username}
          </span>
        )}
        <button onClick={handleLogout} className="p-2 hover:text-red-400 transition-colors" title="Logout">
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
}
