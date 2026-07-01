import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { X, Building2, Award, Users, FileText, TrendingUp, Shield } from 'lucide-react';
import { opportunities } from '../services/api';
import type { Opportunity } from '../types';

interface Props {
  opportunity: Opportunity;
  onClose: () => void;
}

export default function OpportunityModal({ opportunity: opp, onClose }: Props) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const sufficiencyIcons: Record<string, string> = { sufficient: '✓', role_based: '⚠', none: '✗' };
  const sufficiencyColors: Record<string, string> = {
    sufficient: 'text-emerald-400',
    role_based: 'text-amber-400',
    none: 'text-red-400',
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-2xl max-h-[85vh] overflow-y-auto bg-surface-200 border border-surface-300 rounded-2xl p-6 m-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div>
            <h2 className="text-lg font-bold text-white">{opp.company_name ?? 'Opportunity'}</h2>
            <div className="flex items-center gap-3 mt-1 text-sm text-gray-400">
              <span className={`font-mono font-bold ${sufficiencyColors[opp.contact_sufficiency ?? 'none']}`}>
                {sufficiencyIcons[opp.contact_sufficiency ?? 'none']} {opp.contact_sufficiency}
              </span>
              {opp.risk_flag && (
                <span className={`px-2 py-0.5 rounded-full text-xs ${
                  opp.risk_flag === 'red' ? 'badge-red' : opp.risk_flag === 'amber' ? 'badge-amber' : 'badge-green'
                }`}>
                  {opp.risk_flag}
                </span>
              )}
            </div>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-surface-300 rounded-lg transition-colors">
            <X className="w-5 h-5 text-gray-400" />
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Award Detail */}
          <div className="glass rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <Award className="w-4 h-4 text-primary-400" />
              <h3 className="text-sm font-semibold text-gray-200">Award Detail</h3>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">Value</span>
                <span className="text-white font-mono font-medium">
                  {opp.award_value ? `R${(opp.award_value / 1_000).toFixed(0)}K` : '—'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Buyer</span>
                <span className="text-gray-200">{opp.buyer_org ?? '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Days since award</span>
                <span className="text-gray-200">{opp.days_since_award ?? '—'}d</span>
              </div>
            </div>
          </div>

          {/* Company Intel */}
          <div className="glass rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <Building2 className="w-4 h-4 text-primary-400" />
              <h3 className="text-sm font-semibold text-gray-200">Company Intelligence</h3>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">Company</span>
                <span className="text-gray-200">{opp.company_name ?? '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Province</span>
                <span className="text-gray-200">{opp.province ?? '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Category</span>
                <span className="text-gray-200">{opp.category ?? '—'}</span>
              </div>
            </div>
          </div>

          {/* Contact */}
          <div className="glass rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <Users className="w-4 h-4 text-primary-400" />
              <h3 className="text-sm font-semibold text-gray-200">Contact</h3>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">Sufficiency</span>
                <span className={`font-mono ${sufficiencyColors[opp.contact_sufficiency ?? 'none']}`}>
                  {sufficiencyIcons[opp.contact_sufficiency ?? 'none']} {opp.contact_sufficiency}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Assigned</span>
                <span className="text-gray-200">{opp.assigned_to ?? 'Unassigned'}</span>
              </div>
            </div>
          </div>

          {/* Scores */}
          <div className="glass rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <TrendingUp className="w-4 h-4 text-primary-400" />
              <h3 className="text-sm font-semibold text-gray-200">Scoring</h3>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">Funding suitability</span>
                <span className="text-gray-200 font-mono">
                  {opp.funding_suitability != null ? `${opp.funding_suitability}%` : '—'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Win probability</span>
                <span className="text-gray-200 font-mono">
                  {opp.win_probability != null ? `${opp.win_probability}%` : '—'}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Notes */}
        {opp.notes && (
          <div className="glass rounded-xl p-4 mt-4">
            <div className="flex items-center gap-2 mb-3">
              <FileText className="w-4 h-4 text-primary-400" />
              <h3 className="text-sm font-semibold text-gray-200">Notes</h3>
            </div>
            <p className="text-sm text-gray-300 whitespace-pre-wrap">{opp.notes}</p>
          </div>
        )}
      </div>
    </div>
  );
}
