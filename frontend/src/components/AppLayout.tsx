import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { BookOpen, FilePlus, GitCompare, Languages, LogOut, Shield } from 'lucide-react';
import { isCitationAdmin, useAuthStore } from '@/store/authStore';

function navClass(isActive: boolean) {
  return isActive ? 'text-earth-400' : 'text-gray-400 hover:text-white';
}

export default function AppLayout() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const location = useLocation();
  const admin = isCitationAdmin(user);
  const inReview = location.pathname.startsWith('/review');
  const inCitation =
    location.pathname.startsWith('/journals') ||
    location.pathname.startsWith('/manuscripts') ||
    location.pathname.startsWith('/archive');

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="sticky top-0 z-30 flex items-center justify-between px-6 py-3 bg-gray-950/90 backdrop-blur border-b border-gray-800">
        <Link to="/" className="flex items-center gap-3">
          <BookOpen className="w-6 h-6 text-earth-400" />
          <div>
            <h1 className="text-sm font-bold tracking-wide">Citation Assistant</h1>
            <p className="text-xs text-gray-500">Home · two workspaces</p>
          </div>
        </Link>
        <nav className="flex items-center gap-3 text-sm flex-wrap justify-end">
          <NavLink to="/" end className={({ isActive }) => navClass(isActive)}>
            Home
          </NavLink>
          {inCitation && (
            <>
              {admin && (
                <>
                  <NavLink to="/journals" className={({ isActive }) => navClass(isActive)}>
                    Journals
                  </NavLink>
                  <NavLink to="/archive" className={({ isActive }) => navClass(isActive)}>
                    Search
                  </NavLink>
                </>
              )}
              <NavLink to="/manuscripts" className={({ isActive }) => navClass(isActive)}>
                <span className="inline-flex items-center gap-1">
                  <FilePlus className="w-4 h-4" /> New manuscript
                </span>
              </NavLink>
            </>
          )}
          {inReview && (
            <>
              <NavLink to="/review" end className={({ isActive }) => navClass(isActive)}>
                Review home
              </NavLink>
              <NavLink to="/review/references" className={({ isActive }) => navClass(isActive)}>
                <span className="inline-flex items-center gap-1">
                  <GitCompare className="w-4 h-4" /> Reference check
                </span>
              </NavLink>
              <NavLink to="/review/language" className={({ isActive }) => navClass(isActive)}>
                <span className="inline-flex items-center gap-1">
                  <Languages className="w-4 h-4" /> English review
                </span>
              </NavLink>
            </>
          )}
          {admin && (
            <NavLink to="/users" className={({ isActive }) => navClass(isActive)}>
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
      <main className="max-w-7xl mx-auto px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
