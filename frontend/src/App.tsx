import { useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import {
  canManageUsers,
  hasAuthorWing,
  hasReviewBranch,
  hasService,
  isCitationAdmin,
  useAuthStore,
  type AuthorWingId,
  type ReviewBranchId,
  type ServiceId,
} from '@/store/authStore';
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
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

function UsersAdminRoute({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  if (!canManageUsers(user)) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

function ServiceRoute({ service, children }: { service: ServiceId; children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  if (!hasService(user, service)) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

function ReviewBranchRoute({
  branch,
  children,
}: {
  branch: ReviewBranchId;
  children: React.ReactNode;
}) {
  const user = useAuthStore((s) => s.user);
  if (!hasReviewBranch(user, branch)) {
    return <Navigate to="/review" replace />;
  }
  return <>{children}</>;
}

function AuthorWingRoute({ wing, children }: { wing: AuthorWingId; children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  if (!hasAuthorWing(user, wing)) {
    return <Navigate to="/authors" replace />;
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
        <Route
          path="/admin"
          element={
            <UsersAdminRoute>
              <UsersPage />
            </UsersAdminRoute>
          }
        />
        <Route path="/users" element={<Navigate to="/admin" replace />} />
        <Route
          path="/journals"
          element={
            <ServiceRoute service="citation">
              <DashboardPage />
            </ServiceRoute>
          }
        />
        <Route
          path="/journals/:journalId"
          element={
            <ServiceRoute service="citation">
              <JournalVolumesPage />
            </ServiceRoute>
          }
        />
        <Route
          path="/journals/:journalId/volumes/:volume"
          element={
            <ServiceRoute service="citation">
              <VolumeIssuesPage />
            </ServiceRoute>
          }
        />
        <Route
          path="/journals/:journalId/volumes/:volume/issues/:issueNumber"
          element={
            <ServiceRoute service="citation">
              <IssueArticlesPage />
            </ServiceRoute>
          }
        />
        <Route
          path="/manuscripts"
          element={
            <ServiceRoute service="citation">
              <ManuscriptsPage />
            </ServiceRoute>
          }
        />
        <Route
          path="/manuscripts/:manuscriptId"
          element={
            <ServiceRoute service="citation">
              <ManuscriptReviewPage />
            </ServiceRoute>
          }
        />
        <Route
          path="/review"
          element={
            <ServiceRoute service="review">
              <ReviewHubPage />
            </ServiceRoute>
          }
        />
        <Route
          path="/review/references"
          element={
            <ServiceRoute service="review">
              <ReviewBranchRoute branch="references">
                <ReferenceCheckPage />
              </ReviewBranchRoute>
            </ServiceRoute>
          }
        />
        <Route
          path="/review/language"
          element={
            <ServiceRoute service="review">
              <ReviewBranchRoute branch="language">
                <LanguageReviewPage />
              </ReviewBranchRoute>
            </ServiceRoute>
          }
        />
        <Route
          path="/authors"
          element={
            <ServiceRoute service="authors">
              <AuthorHubPage />
            </ServiceRoute>
          }
        />
        <Route
          path="/authors/in-process"
          element={
            <ServiceRoute service="authors">
              <AuthorWingRoute wing="in_process">
                <AuthorArticlesPage wing="in_process" />
              </AuthorWingRoute>
            </ServiceRoute>
          }
        />
        <Route
          path="/authors/in-process/:articleId"
          element={
            <ServiceRoute service="authors">
              <AuthorWingRoute wing="in_process">
                <AuthorArticlesPage wing="in_process" />
              </AuthorWingRoute>
            </ServiceRoute>
          }
        />
        <Route
          path="/authors/published"
          element={
            <ServiceRoute service="authors">
              <AuthorWingRoute wing="published">
                <AuthorArticlesPage wing="published" />
              </AuthorWingRoute>
            </ServiceRoute>
          }
        />
        <Route
          path="/authors/published/:articleId"
          element={
            <ServiceRoute service="authors">
              <AuthorWingRoute wing="published">
                <AuthorArticlesPage wing="published" />
              </AuthorWingRoute>
            </ServiceRoute>
          }
        />
        <Route
          path="/galley"
          element={
            <ServiceRoute service="galley">
              <GalleyPage />
            </ServiceRoute>
          }
        />
        <Route
          path="/archive"
          element={
            <AdminRoute>
              <ArchiveSearchPage />
            </AdminRoute>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
