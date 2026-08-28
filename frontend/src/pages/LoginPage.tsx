import { useState, FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { auth } from '../services/api';
import { TrendingUp } from 'lucide-react';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      // Every path that stores a user writes the address stripped and
      // lowercased, so send it in that form. The backend normalises too; this
      // just keeps what is shown and what is sent identical.
      const res = await auth.login(email.trim().toLowerCase(), password);
      localStorage.setItem('token', res.data.access_token);
      navigate('/pipeline');
    } catch (err) {
      // Only a 401 means the credentials were wrong. Reporting a server fault
      // or an unreachable API as "Invalid credentials" sent people off
      // retyping a password that was correct all along.
      const status = axios.isAxiosError(err) ? err.response?.status : undefined;
      if (status === 401) {
        setError('Invalid credentials');
      } else if (status) {
        setError(`Sign-in failed (server responded ${status}). Please try again.`);
      } else {
        setError('Could not reach the server. Check your connection and try again.');
      }
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-surface-100 via-surface-200 to-surface-100">
      <div className="w-full max-w-md p-8">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary-500/10 mb-4">
            <TrendingUp className="w-8 h-8 text-primary-400" />
          </div>
          <h1 className="text-2xl font-bold text-white">Oricred</h1>
          <p className="text-gray-400 mt-1">Procurement Intelligence Platform</p>
        </div>

        <form onSubmit={handleSubmit} className="glass rounded-2xl p-6 space-y-4">
          <h2 className="text-lg font-semibold text-gray-200">Sign in</h2>

          {error && (
            <div className="bg-red-500/10 text-red-400 text-sm px-4 py-2 rounded-lg border border-red-500/20">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              className="w-full px-3 py-2 bg-surface-300 border border-surface-400 rounded-lg text-gray-100 placeholder-gray-500 focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500/20"
              placeholder="you@example.com"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className="w-full px-3 py-2 bg-surface-300 border border-surface-400 rounded-lg text-gray-100 placeholder-gray-500 focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500/20"
              placeholder="••••••••"
              required
            />
          </div>

          <button
            type="submit"
            className="w-full py-2.5 bg-primary-600 hover:bg-primary-500 text-white font-medium rounded-lg transition-colors"
          >
            Sign in
          </button>
        </form>
      </div>
    </div>
  );
}
