'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Download, History, Loader2, RotateCcw, Upload, X } from 'lucide-react';
import { authFetch } from '@/lib/auth';
import { formatNumber } from '@/lib/corpus';

// The Database tab's Corpus panel (issue #114, backend corpus_admin.py). Owners replace the corpus with a dump made by
// `python -m localrag.export` (upload in parts, resumable, then a restore job that validates and swaps), roll back to
// the previous version, and download the active one. Developers see the same state without the buttons.

export interface CorpusVersion {
  built: string | null;
  model: string | null;
  dim: number | null;
  chunks: number | null;
  kommuner: number;
  uploaded?: { by?: string; at?: string; file?: string } | null;
}

export interface HistoryRow {
  id: number;
  action: 'replace' | 'rollback' | 'download';
  status: 'running' | 'done' | 'failed';
  user_email: string | null;
  file_name: string | null;
  model: string | null;
  chunks: number | null;
  kommuner: number | null;
  built: string | null;
  progress: { phase: string; percent: number; message: string } | null;
  detail: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface PendingUpload {
  id: string;
  file_name: string;
  size: number;
  received: number;
  complete: boolean;
  user_email: string;
  created: string;
}

export interface CorpusStatus {
  active: CorpusVersion | null;
  previous: CorpusVersion | null;
  job: HistoryRow | null;
  uploads: PendingUpload[];
  history: HistoryRow[];
  serving: boolean; // the app reads this corpus (LOCAL_RAG_STORE=neon)
  part_bytes: number;
  upload_free_bytes: number;
  database_bytes: number;
  disk_limit_bytes: number;
}

interface UploadState {
  id: string;
  size: number;
  received: number;
  complete: boolean;
  part_bytes: number;
}

const POLL_MS = 3000;
const PART_RETRIES = 4;

const BUTTON =
  'inline-flex items-center gap-1.5 rounded-lg border border-zinc-300 px-3 py-1.5 text-xs font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800';
const PRIMARY =
  'inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50';

function gb(bytes: number): string {
  return `${(bytes / 1e9).toFixed(bytes < 1e8 ? 3 : 1)} GB`;
}

function when(iso: string | null | undefined): string {
  if (!iso) return '–';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString('sv-SE', { dateStyle: 'short', timeStyle: 'short' });
}

async function detail(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    return typeof data.detail === 'string' ? data.detail : fallback;
  } catch {
    return fallback;
  }
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Sends `file` in parts from what the server already holds, so a second call with the same file resumes. A part whose
 * answer was lost is sent again from the server's offset (409 gives it). Returns the final state.
 */
export async function sendParts(
  file: Blob,
  start: UploadState,
  onProgress: (received: number) => void,
  cancelled: () => boolean,
  wait: (ms: number) => Promise<unknown> = sleep,
): Promise<UploadState> {
  let state = start;
  let failures = 0;
  while (state.received < state.size) {
    if (cancelled()) return state;
    const end = Math.min(state.received + state.part_bytes, state.size);
    let res: Response | null = null;
    try {
      res = await authFetch(`/api/corpus/uploads/${state.id}?offset=${state.received}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: file.slice(state.received, end),
      });
    } catch {
      res = null; // network error: retried below
    }
    if (res?.ok) {
      state = await res.json();
      failures = 0;
      onProgress(state.received);
      continue;
    }
    if (res && res.status !== 409 && res.status < 500) throw new Error(await detail(res, `Upload failed (${res.status})`));
    failures += 1;
    if (failures > PART_RETRIES) throw new Error('The upload keeps failing: try again later, it resumes where it stopped');
    await wait(1000 * 2 ** failures);
    // Where the server is now: the part may have arrived although its answer did not
    const check = await authFetch(`/api/corpus/uploads/${state.id}`);
    if (!check.ok) throw new Error(await detail(check, 'The upload is gone'));
    state = await check.json();
    onProgress(state.received);
  }
  return state;
}

function VersionCard({ title, version, children }: { title: string; version: CorpusVersion | null; children?: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="mb-1 flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">{title}</h3>
        {children}
      </div>
      {version ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
          <dt className="text-zinc-500">Built</dt>
          <dd>{when(version.built)}</dd>
          <dt className="text-zinc-500">Model</dt>
          <dd>
            {version.model} · {version.dim} dims
          </dd>
          <dt className="text-zinc-500">Chunks</dt>
          <dd>
            {formatNumber(version.chunks ?? 0)} · {formatNumber(version.kommuner)} kommuner
          </dd>
          <dt className="text-zinc-500">Uploaded</dt>
          <dd>{version.uploaded?.by ? `${version.uploaded.by}, ${when(version.uploaded.at)}` : 'by hand (before the panel)'}</dd>
        </dl>
      ) : (
        <p className="text-xs italic text-zinc-500">None</p>
      )}
    </div>
  );
}

function JobProgress({ job }: { job: HistoryRow }) {
  if (job.status === 'running') {
    const percent = job.progress?.percent ?? 0;
    return (
      <div className="space-y-1" role="status">
        <div className="flex items-center gap-2 text-xs">
          <Loader2 size={12} className="animate-spin" />
          <span className="font-medium capitalize">{job.progress?.phase ?? 'running'}</span>
          <span className="text-zinc-500">{percent.toFixed(0)} %</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded bg-zinc-200 dark:bg-zinc-800">
          <div className="h-full bg-blue-600 transition-all" style={{ width: `${percent}%` }} />
        </div>
        <p className="truncate text-[11px] text-zinc-500" title={job.progress?.message}>
          {job.progress?.message}
        </p>
      </div>
    );
  }
  if (job.status === 'failed') {
    return (
      <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-950/50 dark:text-red-300">
        The last replace failed ({when(job.finished_at)}): {job.detail}. The live corpus was not changed.
      </p>
    );
  }
  return (
    <p className="text-xs text-green-700 dark:text-green-400">
      Last replace: {job.detail} ({when(job.finished_at)})
    </p>
  );
}

const ACTION_LABEL: Record<HistoryRow['action'], string> = {
  replace: 'Replace',
  rollback: 'Roll back',
  download: 'Download',
};

function HistoryTable({ rows }: { rows: HistoryRow[] }) {
  if (rows.length === 0) return <p className="text-xs italic text-zinc-500">Nothing yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[11px]">
        <thead className="text-zinc-500">
          <tr>
            <th className="py-1 pr-2 font-medium">When</th>
            <th className="py-1 pr-2 font-medium">Who</th>
            <th className="py-1 pr-2 font-medium">Action</th>
            <th className="py-1 pr-2 font-medium">File</th>
            <th className="py-1 pr-2 font-medium">Chunks</th>
            <th className="py-1 font-medium">Result</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-t border-zinc-100 align-top dark:border-zinc-800">
              <td className="whitespace-nowrap py-1 pr-2">{when(row.started_at)}</td>
              <td className="py-1 pr-2">{row.user_email ?? '–'}</td>
              <td className="py-1 pr-2">{ACTION_LABEL[row.action] ?? row.action}</td>
              <td className="max-w-[12rem] truncate py-1 pr-2" title={row.file_name ?? undefined}>
                {row.file_name ?? '–'}
              </td>
              <td className="py-1 pr-2">
                {row.chunks !== null ? formatNumber(row.chunks) : '–'}
                {row.kommuner ? ` · ${row.kommuner} k.` : ''}
              </td>
              <td className={`py-1 ${row.status === 'failed' ? 'text-red-600' : ''}`}>
                {row.status === 'running' ? 'running…' : row.status === 'failed' ? `failed: ${row.detail}` : row.detail ?? 'done'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function CorpusPanel({ canManage, onSwapped }: { canManage: boolean; onSwapped?: () => void }) {
  const [status, setStatus] = useState<CorpusStatus | null>(null);
  const [loadError, setLoadError] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmRollback, setConfirmRollback] = useState(false);
  const [dump, setDump] = useState<File | null>(null);
  const [manifestFile, setManifestFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState<{ received: number; size: number } | null>(null);
  const [pickers, setPickers] = useState(0); // remounts the file inputs once their files are sent
  const cancelRef = useRef(false);
  const lastJob = useRef<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch('/api/corpus');
      if (!res.ok) throw new Error(await detail(res, `Request failed: ${res.status}`));
      const data: CorpusStatus = await res.json();
      setStatus(data);
      setLoadError('');
      // A job that just finished swapped the corpus: the rest of the Database view reloads
      const key = data.job ? `${data.job.id}:${data.job.status}` : null;
      if (lastJob.current?.endsWith(':running') && key?.endsWith(':done')) onSwapped?.();
      lastJob.current = key;
    } catch (err: any) {
      setLoadError(err.message || 'Could not read the corpus status');
    }
  }, [onSwapped]);

  useEffect(() => {
    load();
  }, [load]);

  const running = status?.job?.status === 'running';
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [running, load]);

  const startRestore = async (uploadId: string) => {
    const res = await authFetch(`/api/corpus/uploads/${uploadId}/restore`, { method: 'POST' });
    if (!res.ok) throw new Error(await detail(res, 'Could not start the restore'));
  };

  const handleUpload = async () => {
    if (!dump || !manifestFile) return;
    setError('');
    setBusy(true);
    cancelRef.current = false;
    try {
      let manifest: unknown;
      try {
        manifest = JSON.parse(await manifestFile.text());
      } catch {
        throw new Error('The manifest is not JSON: pick the .manifest.json written by localrag.export');
      }
      const res = await authFetch('/api/corpus/uploads', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_name: dump.name, size: dump.size, manifest }),
      });
      if (!res.ok) throw new Error(await detail(res, 'Could not start the upload'));
      const start: UploadState = await res.json();
      setUploading({ received: start.received, size: start.size });
      const done = await sendParts(
        dump,
        start,
        (received) => setUploading({ received, size: start.size }),
        () => cancelRef.current,
      );
      if (done.received === done.size) {
        await startRestore(done.id);
        setDump(null);
        setManifestFile(null);
        setPickers((n) => n + 1);
      }
    } catch (err: any) {
      setError(err.message || 'The upload failed');
    } finally {
      setUploading(null);
      setBusy(false);
      load();
    }
  };

  const act = async (run: () => Promise<void>) => {
    setError('');
    setBusy(true);
    try {
      await run();
    } catch (err: any) {
      setError(err.message || 'Failed');
    } finally {
      setBusy(false);
      load();
    }
  };

  const handleRollback = () =>
    act(async () => {
      const res = await authFetch('/api/corpus/rollback', { method: 'POST' });
      if (!res.ok) throw new Error(await detail(res, 'Could not roll back'));
      setConfirmRollback(false);
      onSwapped?.();
    });

  const handleDownload = () =>
    act(async () => {
      const res = await authFetch('/api/corpus/download-link', { method: 'POST' });
      if (!res.ok) throw new Error(await detail(res, 'Could not start the download'));
      const { url } = await res.json();
      window.location.assign(url); // the browser saves the stream itself: no 10 GB in memory
    });

  const handleManifest = () =>
    act(async () => {
      const res = await authFetch('/api/corpus/manifest');
      if (!res.ok) throw new Error(await detail(res, 'Could not read the manifest'));
      const manifest = await res.json();
      const blob = new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' });
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = String(manifest.dump_file ?? 'pyrmit-corpus-active.dump').replace(/\.dump$/, '.manifest.json');
      link.click();
      URL.revokeObjectURL(link.href);
    });

  const handleDiscard = (uploadId: string) =>
    act(async () => {
      const res = await authFetch(`/api/corpus/uploads/${uploadId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(await detail(res, 'Could not discard the upload'));
    });

  if (loadError && !status) {
    return (
      <section className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
        <h2 className="mb-2 text-sm font-semibold">Corpus</h2>
        <p role="alert" className="text-xs text-red-600">{loadError}</p>
      </section>
    );
  }
  if (!status) {
    return (
      <section className="rounded-xl border border-zinc-200 p-4 text-xs text-zinc-500 dark:border-zinc-800">
        Loading the corpus versions…
      </section>
    );
  }

  const pending = status.uploads.find((u) => !u.complete);
  const resumable = Boolean(pending && dump && pending.file_name === dump.name && pending.size === dump.size);

  return (
    <section aria-label="Corpus" className="space-y-4 rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">Corpus</h2>
        <span className="text-[11px] text-zinc-500">
          Database {gb(status.database_bytes)} of {gb(status.disk_limit_bytes)} · uploads volume {gb(status.upload_free_bytes)} free
        </span>
      </div>
      {!status.serving && (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          This server reads another store (LOCAL_RAG_STORE is not neon): the corpus below is the one in Postgres, not the
          one the chat uses.
        </p>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <VersionCard title="Active" version={status.active}>
          {canManage && status.active && (
            <span className="flex gap-1.5">
              <button type="button" className={BUTTON} onClick={handleDownload} disabled={busy}>
                <Download size={12} /> Download
              </button>
              <button type="button" className={BUTTON} onClick={handleManifest} disabled={busy}>
                Manifest
              </button>
            </span>
          )}
        </VersionCard>
        <VersionCard title="Previous" version={status.previous}>
          {canManage && status.previous && !confirmRollback && (
            <button type="button" className={BUTTON} onClick={() => setConfirmRollback(true)} disabled={busy || running}>
              <RotateCcw size={12} /> Roll back
            </button>
          )}
          {canManage && status.previous && confirmRollback && (
            <span className="flex items-center gap-1.5">
              <button type="button" className={PRIMARY} onClick={handleRollback} disabled={busy}>
                Make it live
              </button>
              <button type="button" className={BUTTON} onClick={() => setConfirmRollback(false)} aria-label="Cancel">
                <X size={12} />
              </button>
            </span>
          )}
        </VersionCard>
      </div>

      {status.job && <JobProgress job={status.job} />}

      {canManage && (
        <div className="space-y-2 rounded-xl bg-zinc-50 p-3 dark:bg-zinc-800/40">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Replace</h3>
          <p className="text-[11px] text-zinc-500">
            Pick the .dump and the .manifest.json written by <code>python -m localrag.export</code>. The server restores
            it beside the live corpus, checks it, then swaps; the live corpus becomes the previous version.
          </p>
          {status.uploads.map((upload) => (
            <div key={upload.id} className="flex flex-wrap items-center gap-2 text-[11px]">
              <span>
                {upload.complete ? 'Uploaded' : 'Unfinished upload'}: {upload.file_name}, {gb(upload.received)} of{' '}
                {gb(upload.size)} ({upload.user_email})
                {!upload.complete && ' · pick the same file to resume'}
              </span>
              {upload.complete && !running && (
                <button type="button" className={BUTTON} disabled={busy} onClick={() => act(() => startRestore(upload.id))}>
                  Restore it
                </button>
              )}
              {!running && (
                <button type="button" className={BUTTON} disabled={busy} onClick={() => handleDiscard(upload.id)}>
                  Discard
                </button>
              )}
            </div>
          ))}
          <div key={pickers} className="flex flex-wrap items-center gap-3 text-xs">
            <label className="flex items-center gap-1.5">
              Dump
              <input
                type="file"
                accept=".dump"
                aria-label="Dump file"
                disabled={busy || running}
                onChange={(e) => setDump(e.target.files?.[0] ?? null)}
                className="text-[11px]"
              />
            </label>
            <label className="flex items-center gap-1.5">
              Manifest
              <input
                type="file"
                accept=".json,application/json"
                aria-label="Manifest file"
                disabled={busy || running}
                onChange={(e) => setManifestFile(e.target.files?.[0] ?? null)}
                className="text-[11px]"
              />
            </label>
            <button
              type="button"
              className={PRIMARY}
              onClick={handleUpload}
              disabled={busy || running || !dump || !manifestFile}
            >
              <Upload size={12} /> {resumable ? 'Resume upload' : 'Upload and replace'}
            </button>
            {uploading && (
              <button type="button" className={BUTTON} onClick={() => (cancelRef.current = true)}>
                Pause
              </button>
            )}
          </div>
          {uploading && (
            <div className="space-y-1" role="status">
              <div className="h-1.5 w-full overflow-hidden rounded bg-zinc-200 dark:bg-zinc-800">
                <div
                  className="h-full bg-blue-600 transition-all"
                  style={{ width: `${(100 * uploading.received) / uploading.size}%` }}
                />
              </div>
              <p className="text-[11px] text-zinc-500">
                Uploading {gb(uploading.received)} of {gb(uploading.size)}
              </p>
            </div>
          )}
        </div>
      )}

      {error && <p role="alert" className="text-xs text-red-600">{error}</p>}

      <div className="space-y-1">
        <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-zinc-500">
          <History size={12} /> History
        </h3>
        <HistoryTable rows={status.history} />
      </div>
    </section>
  );
}
