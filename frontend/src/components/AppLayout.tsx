import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { BookOpen, FilePlus, LogOut, Shield } from 'lucide-react';
import { isCitationAdmin, useAuthStore } from '@/store/authStore';

export default function AppLayout() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const admin = isCitationAdmin(user);
  const home = admin ? '/' : '/manuscripts';

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="sticky top-0 z-30 flex items-center justify-between px-6 py-3 bg-gray-950/90 backdrop-blur border-b border-gray-800">
        <Link to={home} className="flex items-center gap-3">
          <BookOpen className="w-6 h-6 text-earth-400" />
          <div>
            <h1 className="text-sm font-bold tracking-wide">Citation Assistant</h1>
            <p className="text-xs text-gray-500">IJIST archive · house citations</p>
          </div>
        </Link>
        <nav className="flex items-center gap-4 text-sm">
          {admin && (
            <>
              <NavLink
                to="/"
                end
                className={({ isActive }) =>
                  isActive ? 'text-earth-400' : 'text-gray-400 hover:text-white'
                }
              >
                Journals
              </NavLink>
              <NavLink
                to="/archive"
                className={({ isActive }) =>
                  isActive ? 'text-earth-400' : 'text-gray-400 hover:text-white'
                }
              >
                Search
              </NavLink>
            </>
          )}
          <NavLink
            to="/manuscripts"
            className={({ isActive }) =>
              isActive ? 'text-earth-400' : 'text-gray-400 hover:text-white'
            }
          >
            <span className="inline-flex items-center gap-1">
              <FilePlus className="w-4 h-4" /> New manuscript
            </span>
          </NavLink>
          {admin && (
            <NavLink
              to="/users"
              className={({ isActive }) =>
                isActive ? 'text-earth-400' : 'text-gray-400 hover:text-white'
              }
            >
              <span className="inline-flex items-center gap-1">
                <Shield className="w-4 h-4" /> Users
              </span>
            </NavLink>
          )}
          {user && (
            <span className="text-gray-500">
              {user.full_name || user.username}
              {admin ? ' · admin' : ' · user'}
            </span>
          )}
          <button
            onClick={() => {
              logout();
              navigate('/login');
            }}
            className="p-2 hover:text-red-400"
            title="Logout"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </nav>
      </header>
      <main className="max-w-6xl mx-auto px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
