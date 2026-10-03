import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { BookOpen, CheckSquare, ClipboardList, FilePlus, FilePenLine, GitCompare, Globe, Languages, LogOut, Shield, ShieldAlert } from 'lucide-react';
import {
  canManageUsers,
  hasAuthorWing,
  hasReviewBranch,
  hasService,
  isCitationAdmin,
  isFullAdmin,
  useAuthStore,
} from '@/store/authStore';

function navClass(isActive: boolean) {
  return isActive ? 'text-earth-400' : 'text-gray-400 hover:text-white';
}

export default function AppLayout() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const location = useLocation();
  const admin = isCitationAdmin(user);
  const usersAdmin = canManageUsers(user);
  const citation = hasService(user, 'citation');
  const review = hasService(user, 'review');
  const authors = hasService(user, 'authors');
  const galley = hasService(user, 'galley');
  const inAdmin = location.pathname.startsWith('/admin') || location.pathname.startsWith('/users');
  const inReview = location.pathname.startsWith('/review');
  const inAuthors = location.pathname.startsWith('/authors');
  const inGalley = location.pathname.startsWith('/galley');
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
            <p className="text-xs text-gray-500">Home · workspaces</p>
          </div>
        </Link>
        <nav className="flex items-center gap-3 text-sm flex-wrap justify-end">
          <NavLink to="/" end className={({ isActive }) => navClass(isActive)}>
            Home
          </NavLink>
          <NavLink to="/crawler" className={({ isActive }) => navClass(isActive)}>
            <span className="inline-flex items-center gap-1">
              <Globe className="w-4 h-4" /> Web Crawler
            </span>
          </NavLink>
          {authors && (
            <NavLink to="/authors" className={({ isActive }) => navClass(isActive)}>
              Author DB
            </NavLink>
          )}
          {galley && (
            <NavLink to="/galley" className={({ isActive }) => navClass(isActive)}>
              Galley composition
            </NavLink>
          )}
          {inCitation && citation && (
            <>
              <NavLink to="/journals" className={({ isActive }) => navClass(isActive)}>
                Journals
              </NavLink>
              {admin && (
                <NavLink to="/archive" className={({ isActive }) => navClass(isActive)}>
                  Search
                </NavLink>
              )}
              <NavLink to="/manuscripts" className={({ isActive }) => navClass(isActive)}>
                <span className="inline-flex items-center gap-1">
                  <FilePlus className="w-4 h-4" /> New manuscript
                </span>
              </NavLink>
            </>
          )}
          {inReview && review && (
            <>
              <NavLink to="/review" end className={({ isActive }) => navClass(isActive)}>
                Review home
              </NavLink>
              {hasReviewBranch(user, 'references') && (
                <NavLink to="/review/references" className={({ isActive }) => navClass(isActive)}>
                  <span className="inline-flex items-center gap-1">
                    <GitCompare className="w-4 h-4" /> Reference check
                  </span>
                </NavLink>
              )}
              {hasReviewBranch(user, 'language') && (
                <NavLink to="/review/language" className={({ isActive }) => navClass(isActive)}>
                  <span className="inline-flex items-center gap-1">
                    <Languages className="w-4 h-4" /> English review
                  </span>
                </NavLink>
              )}
            </>
          )}
          {inAuthors && authors && (
            <>
              {hasAuthorWing(user, 'in_process') && (
                <NavLink to="/authors/in-process" className={({ isActive }) => navClass(isActive)}>
                  <span className="inline-flex items-center gap-1">
                    <ClipboardList className="w-4 h-4" /> Under process
                  </span>
                </NavLink>
              )}
              {hasAuthorWing(user, 'published') && (
                <NavLink to="/authors/published" className={({ isActive }) => navClass(isActive)}>
                  <span className="inline-flex items-center gap-1">
                    <CheckSquare className="w-4 h-4" /> Published
                  </span>
                </NavLink>
              )}
              <NavLink to="/authors/sanitization" className={({ isActive }) => navClass(isActive)}>
                <span className="inline-flex items-center gap-1">
                  <ShieldAlert className="w-4 h-4" /> Sanitization
                </span>
              </NavLink>
            </>
          )}
          {inGalley && galley && (
            <span className="inline-flex items-center gap-1 text-earth-400">
              <FilePenLine className="w-4 h-4" /> Desk
            </span>
          )}
          {usersAdmin && (
            <NavLink to="/admin" className={({ isActive }) => navClass(isActive) + (inAdmin ? '' : '')}>
              <span className="inline-flex items-center gap-1">
                <Shield className="w-4 h-4" /> Admin
              </span>
            </NavLink>
          )}
          {user && (
            <span className="text-gray-500">
              {user.full_name || user.username}
              {isFullAdmin(user) ? ' · operator' : usersAdmin ? ' · admin' : ' · user'}
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
      <main className={inGalley ? 'w-full' : 'max-w-7xl mx-auto px-6 py-6'}>
        <Outlet />
      </main>
    </div>
  );
}
