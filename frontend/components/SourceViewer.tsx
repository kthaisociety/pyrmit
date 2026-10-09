'use client';

import { useEffect, useState } from 'react';
import { ExternalLink, FileText, Loader2, X } from 'lucide-react';
import { authFetch } from '@/lib/auth';
import ChunkCard from '@/components/ChunkCard';

// One numbered source of an agent answer: what "[n]" stands for (pipeline event "citations")
export interface CitedChunk {
  chunk_id: string;
  doc_id?: string;
  kind?: string;
  source: string;
  chunk_index?: number | null;
  url?: string | null;
  content: string;
}

export interface Citation {
  n: number;
  label: string;
  chunks: CitedChunk[];
}

interface Location {
  type: 'pdf' | 'url' | 'none';
  page?: number;
  found?: boolean;
  highlighted?: boolean;
  pdf_url?: string;
  view?: { zoom: number; left: number; top: number } | null; // zoom on the highlighted passage
  url?: string;
  source_url?: string | null;
}

// Side panel: the cited chunks, and the original document opened where the chunk is
// (PDF at its page with the chunk highlighted, or the web page / statute scrolled to it by Chrome)
export default function SourceViewer({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  const [pdf, setPdf] = useState<{ blobUrl: string; url: string; page: number; note: string } | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // A new citation closes the previous PDF; object URLs are released
  useEffect(() => {
    setPdf(null);
    setError(null);
  }, [citation]);
  useEffect(() => () => { if (pdf) URL.revokeObjectURL(pdf.blobUrl); }, [pdf]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const open = async (chunk: CitedChunk) => {
    setLoading(chunk.chunk_id);
    setError(null);
    try {
      const response = await authFetch(`/api/docs/locate?chunk_id=${encodeURIComponent(chunk.chunk_id)}`);
      if (!response.ok) throw new Error(`locate failed (${response.status})`);
      const location: Location = await response.json();
      if (location.type === 'pdf' && location.pdf_url) {
        // Fetched with the auth header, shown from a blob URL: the browser's PDF viewer opens it at #page
        const file = await authFetch(location.pdf_url);
        if (!file.ok) throw new Error(`PDF failed (${file.status})`);
        const blobUrl = URL.createObjectURL(await file.blob());
        const page = location.page ?? 1;
        const zoom = location.view ? `&zoom=${location.view.zoom},${location.view.left},${location.view.top}` : '';
        setPdf({
          blobUrl,
          url: `${blobUrl}#page=${page}${zoom}&navpanes=0`, // no thumbnail pane: more room for the page
          page,
          note: !location.found
            ? 'Passage not located in the PDF: opened at the first page.'
            : location.highlighted
              ? `Page ${page}, cited passage highlighted.`
              : `Page ${page} (scanned document: no highlight).`,
        });
      } else if (location.type === 'url' && location.url) {
        window.open(location.url, '_blank', 'noopener,noreferrer');
      } else {
        setError('No original document is available for this source.');
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <aside
        className={`flex h-full w-full flex-col bg-white shadow-xl dark:bg-zinc-900 ${pdf ? 'max-w-6xl' : 'max-w-xl'}`}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-start gap-3 border-b border-zinc-200 px-5 py-4 dark:border-zinc-700">
          <span className="mt-0.5 rounded-md bg-blue-100 px-2 py-0.5 text-xs font-semibold text-blue-700 dark:bg-blue-950 dark:text-blue-300">
            {citation.n}
          </span>
          <h2 className="min-w-0 flex-1 text-sm font-semibold text-zinc-800 dark:text-zinc-100">{citation.label}</h2>
          <button onClick={onClose} className="rounded-lg p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800" title="Close">
            <X size={16} />
          </button>
        </header>

        <div className={`flex min-h-0 flex-1 ${pdf ? 'flex-row' : 'flex-col'}`}>
          <div className={`space-y-3 overflow-y-auto px-5 py-4 ${pdf ? 'w-72 shrink-0 border-r border-zinc-200 dark:border-zinc-700' : ''}`}>
            {citation.chunks.map((chunk) => (
              <div key={chunk.chunk_id} className="space-y-1.5">
                <ChunkCard source={chunk.source} chunkIndex={chunk.chunk_index} content={chunk.content} defaultOpen={!pdf} />
                <button
                  onClick={() => open(chunk)}
                  disabled={loading !== null}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 px-2.5 py-1 text-xs text-zinc-600 hover:border-zinc-400 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300"
                >
                  {loading === chunk.chunk_id ? <Loader2 size={12} className="animate-spin" /> :
                    chunk.doc_id?.startsWith('pdf:') ? <FileText size={12} /> : <ExternalLink size={12} />}
                  {chunk.doc_id?.startsWith('pdf:') ? 'Open the PDF at this passage' : 'Open the original at this passage'}
                </button>
              </div>
            ))}
            {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
          </div>

          {pdf && (
            <div className="flex min-w-0 flex-1 flex-col">
              <p className="px-4 py-2 text-xs text-zinc-500 dark:text-zinc-400">{pdf.note}</p>
              {/* key: a new page reloads the viewer (the #page fragment alone does not navigate) */}
              <iframe key={pdf.url} src={pdf.url} className="min-h-0 flex-1 border-0" title={citation.label} />
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
