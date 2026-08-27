import { useEffect } from 'react';
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import Layout from './components/Layout';
import LeadsPage from './pages/LeadsPage';
import PipelinePage from './pages/PipelinePage';
import DiscoverPage from './pages/DiscoverPage';
import AdminPage from './pages/AdminPage';
import LoginPage from './pages/LoginPage';
import HelpPage from './pages/HelpPage';
import { auth, clearApiCaches } from './services/api';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  return localStorage.getItem('token') ? <>{children}</> : <Navigate to="/login" replace />;
}

/**
 * Keeps non-admins out of the Admin page when they reach it by URL.
 *
 * The nav item is already hidden by role, but hiding a link is not access
 * control — the backend refuses every admin endpoint for a non-admin, and this
 * just avoids rendering a page made entirely of 403s. While the role is still
 * loading we render nothing rather than flashing the page.
 */
function AdminRoute({ children }: { children: React.ReactNode }) {
  const { data: user, isPending } = useQuery({
    queryKey: ['me'],
    queryFn: async () => (await auth.me()).data,
    staleTime: 60_000,
  });
  if (isPending) return null;
  return user?.role === 'admin' ? <>{children}</> : <Navigate to="/discover" replace />;
}

export default function App() {
  const token = localStorage.getItem('token'); const navigate = useNavigate();
  const { error } = useQuery({ queryKey: ['me'], queryFn: async () => (await auth.me()).data, enabled: !!token, retry: false });
  useEffect(() => {
    if (error) {
      localStorage.removeItem('token');
      void clearApiCaches().finally(() => navigate('/login'));
    }
  }, [error, navigate]);
  return <Routes><Route path="/login" element={<LoginPage />} /><Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
    <Route index element={<Navigate to="/discover" replace />} />
    <Route path="discover" element={<DiscoverPage />} /><Route path="help" element={<HelpPage />} /><Route path="leads" element={<LeadsPage />} /><Route path="pipeline" element={<PipelinePage />} />
    <Route path="matching" element={<Navigate to="/discover?tab=watching" replace />} /><Route path="awards" element={<Navigate to="/discover?tab=awards" replace />} />
    <Route path="tenders" element={<Navigate to="/discover?tab=tenders" replace />} /><Route path="historical-contacts" element={<Navigate to="/discover?tab=history" replace />} />
    <Route path="past-due" element={<Navigate to="/discover?tab=past-due" replace />} /><Route path="admin" element={<AdminRoute><AdminPage /></AdminRoute>} />
  </Route></Routes>;
}
