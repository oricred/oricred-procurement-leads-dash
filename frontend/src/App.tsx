import { useEffect } from 'react';
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import Layout from './components/Layout';
import LeadsPage from './pages/LeadsPage';
import PipelinePage from './pages/PipelinePage';
import MatchingPage from './pages/MatchingPage';
import AwardsPage from './pages/AwardsPage';
import TendersPage from './pages/TendersPage';
import AdminPage from './pages/AdminPage';
import PastDuePage from './pages/PastDuePage';
import LoginPage from './pages/LoginPage';
import { auth } from './services/api';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('token');
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  const token = localStorage.getItem('token');
  const navigate = useNavigate();

  const { error } = useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      const res = await auth.me();
      return res.data;
    },
    enabled: !!token,
    retry: false,
  });

  useEffect(() => {
    if (error) {
      localStorage.removeItem('token');
      navigate('/login');
    }
  }, [error, navigate]);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/leads" replace />} />
        <Route path="leads" element={<LeadsPage />} />
        <Route path="pipeline" element={<PipelinePage />} />
        <Route path="matching" element={<MatchingPage />} />
        <Route path="awards" element={<AwardsPage />} />
        <Route path="tenders" element={<TendersPage />} />
        <Route path="past-due" element={<PastDuePage />} />
        <Route path="admin" element={<AdminPage />} />
      </Route>
    </Routes>
  );
}

