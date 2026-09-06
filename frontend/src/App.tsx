import { lazy, Suspense, useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { isCitationAdmin, useAuthStore } from '@/store/authStore';
import SatPassPage from '@/satpass/SatPassPage';

// Legacy (non-SatPass) pages are code-split so the SatPass landing page stays light.
const LoginPage = lazy(() => import('@/pages/LoginPage'));
const RegisterPage = lazy(() => import('@/pages/RegisterPage'));
const AppLayout = lazy(() => import('@/components/AppLayout'));
const DashboardPage = lazy(() => import('@/pages/DashboardPage'));
const JournalVolumesPage = lazy(() => import('@/pages/JournalVolumesPage'));
const VolumeIssuesPage = lazy(() => import('@/pages/VolumeIssuesPage'));
const IssueArticlesPage = lazy(() => import('@/pages/IssueArticlesPage'));
const ManuscriptsPage = lazy(() => import('@/pages/ManuscriptsPage'));
const ManuscriptReviewPage = lazy(() => import('@/pages/ManuscriptReviewPage'));
const ArchiveSearchPage = lazy(() => import('@/pages/ArchiveSearchPage'));
const UsersPage = lazy(() => import('@/pages/UsersPage'));
const CopernicusCallbackPage = lazy(() => import('@/pages/CopernicusCallbackPage'));
const BillingSuccessPage = lazy(() => import('@/pages/BillingSuccessPage'));
const BillingCancelPage = lazy(() => import('@/pages/BillingCancelPage'));

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
    <Suspense
      fallback={
        <div className="min-h-screen bg-gray-950 flex items-center justify-center text-gray-400">
          Loading…
        </div>
      }
    >
      <Routes>
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <SatPassPage />
            </ProtectedRoute>
          }
        />
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
          <Route path="/legacy" element={<HomeRoute />} />
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
    </Suspense>
  );
}
