import { Filter, X } from 'lucide-react';

export interface FilterField {
  key: string;
  label: string;
  type: 'text' | 'number' | 'date' | 'select' | 'toggle';
  options?: { label: string; value: string }[];
  placeholder?: string;
}

interface FilterBarProps {
  fields: FilterField[];
  values: Record<string, string>;
  onChange: (key: string, value: string) => void;
  onClear: () => void;
}

export default function FilterBar({ fields, values, onChange, onClear }: FilterBarProps) {
  const hasFilters = Object.values(values).some(v => v !== '');

  return (
    <div className="bg-surface-300 rounded-xl p-3 border border-surface-400">
      <div className="flex items-center gap-2 mb-2">
        <Filter className="w-3.5 h-3.5 text-gray-400" />
        <span className="text-xs font-medium text-gray-400">Filters</span>
        {hasFilters && (
          <button
            onClick={onClear}
            className="ml-auto flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            <X className="w-3 h-3" /> Clear
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {fields.map((field) => (
          <div key={field.key} className="flex-1 min-w-[140px] max-w-[220px]">
            {field.type === 'select' ? (
              <select
                value={values[field.key] ?? ''}
                onChange={(e) => onChange(field.key, e.target.value)}
                className="w-full bg-surface-200 border border-surface-400 rounded-lg px-2.5 py-1.5 text-xs text-gray-300 focus:outline-none focus:border-primary-500"
              >
                <option value="">{field.label}</option>
                {field.options?.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            ) : field.type === 'toggle' ? (
              <label className="flex items-center gap-2 px-2.5 py-1.5 text-xs text-gray-400 cursor-pointer">
                <input
                  type="checkbox"
                  checked={values[field.key] === 'true'}
                  onChange={(e) => onChange(field.key, e.target.checked ? 'true' : '')}
                  className="rounded border-surface-400 bg-surface-200 text-primary-500 focus:ring-primary-500"
                />
                {field.label}
              </label>
            ) : (
              <input
                type={field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text'}
                value={values[field.key] ?? ''}
                onChange={(e) => onChange(field.key, e.target.value)}
                placeholder={field.placeholder ?? field.label}
                className="w-full bg-surface-200 border border-surface-400 rounded-lg px-2.5 py-1.5 text-xs text-gray-300 placeholder-gray-600 focus:outline-none focus:border-primary-500"
              />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
