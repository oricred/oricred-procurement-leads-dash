import { useRef, useState } from 'react';
import { CheckCircle, FileUp, LoaderCircle, X } from 'lucide-react';
import { leads, type LeadContactImportResult } from '../services/api';

interface Props { onImported: () => void; }

type Step = 'choose' | 'preview' | 'importing' | 'results';

function errorMessage(error: unknown): string {
  const data = (error as { response?: { data?: unknown } }).response?.data;
  if (data && typeof data === 'object' && 'detail' in data) {
    const detail = data.detail;
    if (Array.isArray(detail)) {
      return detail.map((d: { msg?: string }) => d.msg ?? String(d)).join('; ');
    }
    if (typeof detail === 'string') return detail;
    return JSON.stringify(detail);
  }
  return 'The import could not be processed.';
}

function rowLabel(row: { company?: string | null; lead_id?: string | null; row: number }): string {
  return row.company ?? row.lead_id ?? `Row ${row.row}`;
}

export default function LeadContactImport({ onImported }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [step, setStep] = useState<Step>('choose');
  const [preview, setPreview] = useState<LeadContactImportResult | null>(null);
  const [result, setResult] = useState<LeadContactImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    setIsOpen(false); setFile(null); setPreview(null); setResult(null); setError(null); setStep('choose');
  };

  const chooseFile = async (selected: File | null) => {
    if (!selected) return;
    setFile(selected); setPreview(null); setResult(null); setError(null); setStep('choose');
    try {
      const res = await leads.previewContactImport(selected);
      setPreview(res.data);
      setStep('preview');
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  const apply = async () => {
    if (!file) return;
    setError(null); setStep('importing');
    try {
      const res = await leads.applyContactImport(file);
      setResult(res.data);
      onImported();
      setStep('results');
    } catch (caught) {
      setError(errorMessage(caught));
      setStep('preview');
    }
  };

  return <>
    <button onClick={() => { setIsOpen(true); setStep('choose'); }} className="inline-flex items-center gap-1.5 rounded border border-surface-300 px-3 py-2 text-xs font-medium text-gray-200 transition-colors hover:bg-surface-300">
      <FileUp className="w-3.5 h-3.5" /> Import Contacts
    </button>
    {isOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="flex w-full max-w-2xl flex-col rounded-lg border border-surface-300 bg-surface-200 shadow-xl max-h-[90vh]">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 border-b border-surface-300 px-5 py-4">
          <div>
            <h3 className="font-semibold text-white">Import enriched contacts</h3>
            <p className="mt-0.5 text-xs text-gray-500">Upload the exported lead CSV or an enriched XLSX file. Blank fields never replace existing values.</p>
          </div>
          <button onClick={close} disabled={step === 'importing'} className="text-gray-500 hover:text-white disabled:opacity-40"><X className="w-5 h-5" /></button>
        </div>

        {/* File picker */}
        {step !== 'results' && <div className="px-5 pt-4">
          <input ref={inputRef} type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" className="hidden" onChange={(event) => void chooseFile(event.target.files?.[0] ?? null)} />
          <div className="rounded border border-dashed border-surface-300 p-4 text-center">
            <p className="text-sm text-gray-300">{file ? file.name : 'Choose a CSV or XLSX enrichment file'}</p>
            <button onClick={() => inputRef.current?.click()} disabled={step === 'importing'} className="mt-3 rounded bg-surface-300 px-3 py-1.5 text-xs text-white hover:bg-surface-400">Choose file</button>
          </div>
        </div>}

        {/* Body */}
        <div className="overflow-y-auto px-5 pb-2 pt-4 min-h-0">
          {step === 'choose' && file && !preview && !error && (
            <div className="flex items-center gap-2 py-4 text-sm text-gray-400"><LoaderCircle className="h-4 w-4 animate-spin" />Validating file…</div>
          )}

          {error && (
            <div className="rounded bg-red-500/10 px-3 py-2 text-sm text-red-300">{String(error)}</div>
          )}

          {step === 'importing' && preview && (
            <div className="flex flex-col items-center gap-3 py-8 text-center">
              <LoaderCircle className="h-8 w-8 animate-spin text-primary-400" />
              <p className="text-sm text-gray-300">Processing {preview.total_rows} contacts…</p>
              <div className="flex gap-4 text-xs text-gray-500">
                <span>{preview.creates} to create</span>
                <span>{preview.updates} to update</span>
                <span>{preview.skips} to skip</span>
              </div>
            </div>
          )}

          {step === 'preview' && preview && (
            <div className="space-y-3">
              <div className="grid grid-cols-4 gap-2 text-center text-xs">
                <span className="rounded bg-surface-300 p-2 text-gray-300">{preview.total_rows}<br />rows</span>
                <span className="rounded bg-emerald-500/10 p-2 text-emerald-300">{preview.creates}<br />new</span>
                <span className="rounded bg-blue-500/10 p-2 text-blue-300">{preview.updates}<br />updates</span>
                <span className="rounded bg-amber-500/10 p-2 text-amber-300">{preview.skips}<br />skipped</span>
              </div>
              {preview.skips > 0 && preview.rows && (
                <div className="max-h-28 overflow-auto rounded bg-surface-300/60 p-2 text-xs text-gray-400">
                  {preview.rows.filter((r) => r.action === 'skip').map((r) => (
                    <div key={r.row}>{rowLabel(r)}: {r.message}</div>
                  ))}
                </div>
              )}
              <p className="text-xs text-gray-500">Only importer-owned contacts are updated. Existing manual and Tenders-SA contacts remain unchanged.</p>
            </div>
          )}

          {step === 'results' && result && (
            <div className="space-y-3">
              <div className="flex items-center gap-2 rounded bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
                <CheckCircle className="h-4 w-4 shrink-0" />
                Import complete — {result.applied ?? 0} of {result.total_rows} contacts processed
              </div>
              <div className="grid grid-cols-4 gap-2 text-center text-xs">
                <span className="rounded bg-surface-300 p-2 text-gray-300">{result.total_rows}<br />rows</span>
                <span className="rounded bg-emerald-500/10 p-2 text-emerald-300">{result.creates}<br />created</span>
                <span className="rounded bg-blue-500/10 p-2 text-blue-300">{result.updates}<br />updated</span>
                <span className="rounded bg-amber-500/10 p-2 text-amber-300">{result.skips}<br />skipped</span>
              </div>
              {result.rows && (
                <div className="max-h-64 space-y-1 overflow-auto">
                  {result.rows.map((r) => (
                    <div key={r.row} className="flex items-center gap-2 rounded bg-surface-300/40 px-3 py-2 text-xs">
                      <span className="w-8 shrink-0 text-gray-500">#{r.row}</span>
                      <span className="min-w-0 flex-1 truncate text-gray-200">{rowLabel(r)}</span>
                      <span className="shrink-0">{r.action === 'create' ? (
                        <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 font-medium text-emerald-300">New</span>
                      ) : r.action === 'update' ? (
                        <span className="rounded bg-blue-500/10 px-1.5 py-0.5 font-medium text-blue-300">Updated</span>
                      ) : (
                        <span className="rounded bg-gray-500/10 px-1.5 py-0.5 font-medium text-gray-400">Skipped</span>
                      )}</span>
                      {r.action === 'skip' && r.message && (
                        <span className="hidden shrink truncate text-gray-500 sm:inline max-w-[200px]">{r.message}</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Actions */}
        {step !== 'results' && <div className="flex items-center justify-end gap-2 border-t border-surface-300 px-5 py-4">
          <button onClick={close} disabled={step === 'importing'} className="rounded px-3 py-2 text-xs text-gray-400 hover:text-white disabled:opacity-40">Cancel</button>
          {step === 'preview' && preview && (
            <button onClick={() => void apply()} disabled={(preview.creates + preview.updates) === 0} className="inline-flex items-center gap-1.5 rounded bg-primary-500 px-3 py-2 text-xs font-medium text-white hover:bg-primary-400 disabled:cursor-not-allowed disabled:opacity-60">
              <FileUp className="h-3.5 w-3.5" />Import {preview.creates + preview.updates} contact{(preview.creates + preview.updates) !== 1 ? 's' : ''}
            </button>
          )}
        </div>}

        {step === 'results' && <div className="flex items-center justify-end gap-2 border-t border-surface-300 px-5 py-4">
          <button onClick={close} className="rounded bg-primary-500 px-4 py-2 text-xs font-medium text-white hover:bg-primary-400">Done</button>
        </div>}
      </div>
    </div>}
  </>;
}
