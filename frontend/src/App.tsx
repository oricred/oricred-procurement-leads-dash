import { useEffect } from 'react';
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import Layout from './components/Layout';
import PipelinePage from './pages/PipelinePage';
import WatchingPage from './pages/WatchingPage';
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
        <Route index element={<Navigate to="/pipeline" replace />} />
        <Route path="pipeline" element={<PipelinePage />} />
        <Route path="watching" element={<WatchingPage />} />
      </Route>
    </Routes>
  );
}
