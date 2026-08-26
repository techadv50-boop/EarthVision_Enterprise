import { useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuthStore } from '@/store/authStore';
import DashboardPage from '@/pages/DashboardPage';
import LoginPage from '@/pages/LoginPage';
import RegisterPage from '@/pages/RegisterPage';
import ResetPasswordPage from '@/pages/ResetPasswordPage';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, fetchUser, isLoading, requireLogin } = useAuthStore();

  useEffect(() => {
    void fetchUser();
  }, [fetchUser]);

  if (isLoading) {
    return (
      <div className="min-h-screen sateye-shell flex items-center justify-center">
        <div className="text-center animate-fade-in">
          <div className="brand-mark text-5xl tracking-[0.2em] mb-3">SAT EYE</div>
          <p className="text-sm text-sateye-mist/70">Connecting to server…</p>
        </div>
      </div>
    );
  }

  if (requireLogin && !isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <DashboardPage />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
