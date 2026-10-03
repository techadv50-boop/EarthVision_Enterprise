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
import HomePage from '@/pages/HomePage';
import ReviewHubPage from '@/pages/ReviewHubPage';
import ReferenceCheckPage from '@/pages/ReferenceCheckPage';
import LanguageReviewPage from '@/pages/LanguageReviewPage';
import AuthorHubPage from '@/pages/AuthorHubPage';
import AuthorArticlesPage from '@/pages/AuthorArticlesPage';
import GalleyPage from '@/pages/GalleyPage';
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
        <Route path="/" element={<HomePage />} />
        <Route path="/journals" element={<DashboardPage />} />
        <Route path="/journals/:journalId" element={<JournalVolumesPage />} />
        <Route
          path="/journals/:journalId/volumes/:volume"
          element={<VolumeIssuesPage />}
        />
        <Route
          path="/journals/:journalId/volumes/:volume/issues/:issueNumber"
          element={<IssueArticlesPage />}
        />
        <Route path="/manuscripts" element={<ManuscriptsPage />} />
        <Route path="/manuscripts/:manuscriptId" element={<ManuscriptReviewPage />} />
        <Route path="/review" element={<ReviewHubPage />} />
        <Route path="/review/references" element={<ReferenceCheckPage />} />
        <Route path="/review/language" element={<LanguageReviewPage />} />
        <Route path="/authors" element={<AuthorHubPage />} />
        <Route path="/authors/in-process" element={<AuthorArticlesPage wing="in_process" />} />
        <Route path="/authors/published" element={<AuthorArticlesPage wing="published" />} />
        <Route path="/galley" element={<GalleyPage />} />
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
