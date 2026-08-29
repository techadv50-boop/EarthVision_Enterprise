import { useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { isCitationAdmin, useAuthStore } from '@/store/authStore';
import LoginPage from '@/pages/LoginPage';
import RegisterPage from '@/pages/RegisterPage';
import AppLayout from '@/components/AppLayout';
import DashboardPage from '@/pages/DashboardPage';
import JournalVolumesPage from '@/pages/JournalVolumesPage';
import VolumeIssuesPage from '@/pages/VolumeIssuesPage';
import IssueArticlesPage from '@/pages/IssueArticlesPage';
import ManuscriptsPage from '@/pages/ManuscriptsPage';
import ManuscriptReviewPage from '@/pages/ManuscriptReviewPage';
import ArchiveSearchPage from '@/pages/ArchiveSearchPage';
import UsersPage from '@/pages/UsersPage';
import CopernicusCallbackPage from '@/pages/CopernicusCallbackPage';
import BillingSuccessPage from '@/pages/BillingSuccessPage';
import BillingCancelPage from '@/pages/BillingCancelPage';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, fetchUser, isLoading } = useAuthStore();

  useEffect(() => {
    void fetchUser();
  }, [fetchUser]);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center text-gray-400">
        Loading...
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  if (!isCitationAdmin(user)) {
    return <Navigate to="/manuscripts" replace />;
  }
  return <>{children}</>;
}

function HomeRoute() {
  const user = useAuthStore((s) => s.user);
  if (!isCitationAdmin(user)) {
    return <Navigate to="/manuscripts" replace />;
  }
  return <DashboardPage />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/billing/success" element={<BillingSuccessPage />} />
      <Route path="/billing/cancel" element={<BillingCancelPage />} />
      <Route path="/auth/copernicus/callback" element={<CopernicusCallbackPage />} />
      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/" element={<HomeRoute />} />
        <Route
          path="/journals/:journalId"
          element={
            <AdminRoute>
              <JournalVolumesPage />
            </AdminRoute>
          }
        />
        <Route
          path="/journals/:journalId/volumes/:volume"
          element={
            <AdminRoute>
              <VolumeIssuesPage />
            </AdminRoute>
          }
        />
        <Route
          path="/journals/:journalId/volumes/:volume/issues/:issueNumber"
          element={
            <AdminRoute>
              <IssueArticlesPage />
            </AdminRoute>
          }
        />
        <Route path="/manuscripts" element={<ManuscriptsPage />} />
        <Route path="/manuscripts/:manuscriptId" element={<ManuscriptReviewPage />} />
        <Route
          path="/archive"
          element={
            <AdminRoute>
              <ArchiveSearchPage />
            </AdminRoute>
          }
        />
        <Route
          path="/users"
          element={
            <AdminRoute>
              <UsersPage />
            </AdminRoute>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
