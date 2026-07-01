import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { TrendingUp, Columns, Eye, LogOut, Activity, Shield } from 'lucide-react';
import { auth, dashboard } from '../services/api';
import { useState } from 'react';

export default function Layout() {
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const { data: user } = useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      const res = await auth.me();
      return res.data;
    },
    staleTime: 60_000,
  });

  const { data: stats } = useQuery({
    queryKey: ['dashboard-stats'],
    queryFn: async () => {
      const res = await dashboard.stats();
      return res.data;
    },
    refetchInterval: 30_000,
  });

  const isAdmin = user?.role === 'admin';

  const handleLogout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className={`w-64 bg-surface-200 border-r border-surface-300 flex flex-col ${sidebarOpen ? 'block' : 'hidden'} md:flex`}>
        <div className="p-5 border-b border-surface-300">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-primary-500/10 flex items-center justify-center">
              <TrendingUp className="w-5 h-5 text-primary-400" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-white">Oricred</h1>
              <p className="text-xs text-gray-500">Procurement Intel</p>
            </div>
          </div>
        </div>

        <nav className="flex-1 p-3 space-y-1">
          {[
            { path: '/pipeline', label: 'Pipeline', icon: Columns },
            { path: '/watching', label: 'Watching', icon: Eye },
            ...(isAdmin ? [{ path: '/admin', label: 'Admin', icon: Shield }] : []),
          ].map(({ path, label, icon: Icon }) => (
            <NavLink
              key={path}
              to={path}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-primary-500/10 text-primary-400 border border-primary-500/20'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-surface-300'
                }`
              }
            >
              <Icon className="w-4 h-4" />
              {label}
            </NavLink>
          ))}
        </nav>

        {stats && (
          <div className="px-4 py-3 border-t border-surface-300">
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <Activity className="w-3 h-3" />
              <span>{stats.total_watching} watching &middot; {stats.past_due_count} past due</span>
            </div>
          </div>
        )}

        <div className="p-3 border-t border-surface-300">
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm text-gray-400 hover:text-gray-200 hover:bg-surface-300 transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col overflow-hidden">
        <header className="h-14 border-b border-surface-300 flex items-center justify-between px-6 bg-surface-200/50 backdrop-blur-sm">
          <button className="md:hidden text-gray-400" onClick={() => setSidebarOpen(!sidebarOpen)}>
            <Columns className="w-5 h-5" />
          </button>
          <div className="flex items-center gap-4 text-sm">
            {stats && (
              <>
                <span className="text-gray-400">{stats.total_opportunities} opportunities</span>
                {stats.past_due_count > 0 && (
                  <span className="badge-red text-xs px-2 py-0.5 rounded-full">
                    {stats.past_due_count} past due
                  </span>
                )}
              </>
            )}
          </div>
        </header>

        <div className="flex-1 overflow-auto p-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
