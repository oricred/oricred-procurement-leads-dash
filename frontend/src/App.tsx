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
import { auth } from './services/api';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  return localStorage.getItem('token') ? <>{children}</> : <Navigate to="/login" replace />;
}
export default function App() {
  const token = localStorage.getItem('token'); const navigate = useNavigate();
  const { error } = useQuery({ queryKey: ['me'], queryFn: async () => (await auth.me()).data, enabled: !!token, retry: false });
  useEffect(() => { if (error) { localStorage.removeItem('token'); navigate('/login'); } }, [error, navigate]);
  return <Routes><Route path="/login" element={<LoginPage />} /><Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
    <Route index element={<Navigate to="/discover" replace />} />
    <Route path="discover" element={<DiscoverPage />} /><Route path="help" element={<HelpPage />} /><Route path="leads" element={<LeadsPage />} /><Route path="pipeline" element={<PipelinePage />} />
    <Route path="matching" element={<Navigate to="/discover?tab=watching" replace />} /><Route path="awards" element={<Navigate to="/discover?tab=awards" replace />} />
    <Route path="tenders" element={<Navigate to="/discover?tab=tenders" replace />} /><Route path="historical-contacts" element={<Navigate to="/discover?tab=history" replace />} />
    <Route path="past-due" element={<Navigate to="/discover?tab=past-due" replace />} /><Route path="admin" element={<AdminPage />} />
  </Route></Routes>;
}
