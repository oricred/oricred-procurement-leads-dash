import { useRef, useState } from 'react';
import { FileUp, LoaderCircle, X } from 'lucide-react';
import { leads, type LeadContactImportResult } from '../services/api';

interface Props { onImported: () => void; }

function errorMessage(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
  return detail ?? 'The import could not be processed.';
}

export default function LeadContactImport({ onImported }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<LeadContactImportResult | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    setIsOpen(false); setFile(null); setPreview(null); setError(null);
  };

  const chooseFile = async (selected: File | null) => {
    if (!selected) return;
    setFile(selected); setPreview(null); setError(null); setIsPreviewing(true);
    try {
      const response = await leads.previewContactImport(selected);
      setPreview(response.data);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setIsPreviewing(false);
    }
  };

  const apply = async () => {
    if (!file) return;
    setError(null); setIsApplying(true);
    try {
      await leads.applyContactImport(file);
      onImported(); close();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setIsApplying(false);
    }
  };

  return <>
    <button onClick={() => setIsOpen(true)} className="inline-flex items-center gap-1.5 rounded border border-surface-300 px-3 py-2 text-xs font-medium text-gray-200 transition-colors hover:bg-surface-300">
      <FileUp className="w-3.5 h-3.5" /> Import Contacts
    </button>
    {isOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-xl rounded-lg border border-surface-300 bg-surface-200 p-5 shadow-xl">
        <div className="flex items-start justify-between gap-4"><div><h3 className="font-semibold text-white">Import enriched contacts</h3><p className="mt-1 text-xs text-gray-500">Upload the exported lead CSV or an enriched XLSX file. Blank fields never replace existing values.</p></div><button onClick={close} className="text-gray-500 hover:text-white"><X className="w-5 h-5" /></button></div>
        <input ref={inputRef} type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" className="hidden" onChange={(event) => void chooseFile(event.target.files?.[0] ?? null)} />
        <div className="mt-5 rounded border border-dashed border-surface-300 p-4 text-center">
          <p className="text-sm text-gray-300">{file ? file.name : 'Choose a CSV or XLSX enrichment file'}</p>
          <button onClick={() => inputRef.current?.click()} disabled={isPreviewing || isApplying} className="mt-3 rounded bg-surface-300 px-3 py-1.5 text-xs text-white hover:bg-surface-400">Choose file</button>
        </div>
        {isPreviewing && <p className="mt-4 flex items-center gap-2 text-sm text-gray-400"><LoaderCircle className="w-4 h-4 animate-spin" /> Validating file…</p>}
        {error && <p className="mt-4 rounded bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</p>}
        {preview && <div className="mt-4 space-y-3"><div className="grid grid-cols-4 gap-2 text-center text-xs"><span className="rounded bg-surface-300 p-2 text-gray-300">{preview.total_rows}<br />rows</span><span className="rounded bg-emerald-500/10 p-2 text-emerald-300">{preview.creates}<br />new</span><span className="rounded bg-blue-500/10 p-2 text-blue-300">{preview.updates}<br />updates</span><span className="rounded bg-amber-500/10 p-2 text-amber-300">{preview.skips}<br />skipped</span></div>{preview.skips > 0 && <div className="max-h-32 overflow-auto rounded bg-surface-300/60 p-2 text-xs text-gray-400">{preview.rows.filter((row) => row.action === 'skip').map((row) => <div key={row.row}>Row {row.row}: {row.message}</div>)}</div>}<p className="text-xs text-gray-500">Only importer-owned contacts are updated. Existing manual and Tenders-SA contacts remain unchanged.</p></div>}
        <div className="mt-5 flex justify-end gap-2"><button onClick={close} disabled={isApplying} className="rounded px-3 py-2 text-xs text-gray-400 hover:text-white">Cancel</button><button onClick={() => void apply()} disabled={!preview || !file || isApplying || preview.creates + preview.updates === 0} className="inline-flex items-center gap-1.5 rounded bg-primary-500 px-3 py-2 text-xs font-medium text-white hover:bg-primary-400 disabled:cursor-not-allowed disabled:opacity-60">{isApplying && <LoaderCircle className="w-3.5 h-3.5 animate-spin" />}{isApplying ? 'Importing…' : 'Confirm import'}</button></div>
      </div>
    </div>}
  </>;
}
