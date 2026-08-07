import { useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuthStore } from '@/store/authStore';
import DashboardPage from '@/pages/DashboardPage';

function OfflineGate({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, fetchUser, isLoading } = useAuthStore();

  useEffect(() => {
    void fetchUser();
  }, [fetchUser]);

  if (isLoading) {
    return (
      <div className="min-h-screen sateye-shell flex items-center justify-center">
        <div className="text-center animate-fade-in">
          <div className="brand-mark text-5xl tracking-[0.2em] mb-3">SAT EYE</div>
          <p className="text-sm text-sateye-mist/70">Starting offline workspace…</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route
        path="/"
        element={
          <OfflineGate>
            <DashboardPage />
          </OfflineGate>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
