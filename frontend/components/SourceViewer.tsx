'use client';

import { useEffect, useRef, useState } from 'react';
import { ExternalLink, FileText, Loader2, X } from 'lucide-react';
import { authFetch } from '@/lib/auth';
import { fill, useLanguage } from '@/lib/i18n';
import Term from '@/components/Term';
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
  needs_download?: boolean; // asked with download=false: the PDF must first come from the kommun's site
  source_host?: string | null;
}

async function locateChunk(chunkId: string, download = true): Promise<Location> {
  const query = new URLSearchParams({ chunk_id: chunkId, ...(download ? {} : { download: 'false' }) });
  const response = await authFetch(`/api/docs/locate?${query}`);
  if (!response.ok) throw new Error(`locate failed (${response.status})`);
  return response.json();
}

// A crawled PDF, or a web page / statute with its address. The 7 "legacy:" documents of the early prototype (963
// Vallentuna chunks, in every corpus) were added by hand without their file or URL: nothing to open
// open (citations saved by older versions carry no doc_id: the backend decides)
function hasOriginal(chunk: CitedChunk): boolean {
  if (chunk.doc_id === undefined) return true;
  return !chunk.doc_id.startsWith('legacy:') && (chunk.doc_id.startsWith('pdf:') || Boolean(chunk.url));
}

// A web page or statute in a new tab, scrolled to the chunk's wording (Chrome text fragment)
export async function openPageAtChunk(chunkId: string): Promise<void> {
  const location = await locateChunk(chunkId);
  if (location.type === 'url' && location.url) window.open(location.url, '_blank', 'noopener,noreferrer');
  else throw new Error('No original page is available for this source.');
}

// A text with "{kommun}" in it: the word shown as a glossary Term (the English texts keep the Swedish word)
function WithKommun({ text }: { text: string }) {
  const [before, after] = text.split('{kommun}');
  return after === undefined ? <>{text}</> : <>{before}<Term term="kommun" />{after}</>;
}

// Side panel: the cited chunks, and the original document opened where the chunk is
// (PDF at its page with the chunk highlighted, or the web page / statute scrolled to it by Chrome).
// n = 0: not a citation (Database view); autoOpen: open the first chunk's document right away.
// supporting: chunk_id -> the sentences of that chunk that back a claim of the answer (claim check, issue #84),
// underlined in that chunk's card only; a chunk missing from it, or no `supporting` at all, shows no underline
export default function SourceViewer({ citation, onClose, autoOpen = false, supporting = {} }: {
  citation: Citation;
  onClose: () => void;
  autoOpen?: boolean;
  supporting?: Record<string, string[]>;
}) {
  const { t } = useLanguage();
  const [pdf, setPdf] = useState<{ blobUrl: string; url: string; page: number; note: string } | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null); // what the open click is waiting for
  const [error, setError] = useState<string | null>(null);
  // locate found the chunk's wording on no page of its PDF: the notice, and the PDF to open from page 1 on request
  const [notFound, setNotFound] = useState<{ chunkId: string; pdfUrl: string } | null>(null);

  // The latest click: a slower earlier request (or one for the previous citation) must not replace its result
  const request = useRef(0);

  // A new citation closes the previous PDF; object URLs are released
  useEffect(() => {
    request.current += 1;
    setPdf(null);
    setError(null);
    setNotFound(null);
    setLoading(null);
  }, [citation]);
  useEffect(() => () => { if (pdf) URL.revokeObjectURL(pdf.blobUrl); }, [pdf]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Fetched with the auth header, shown from a blob URL: the browser's PDF viewer opens it at #page
  const showPdf = async (pdfUrl: string, page: number, view: Location['view'], note: string, mine: number) => {
    setStatus(t('source.openingPdf'));
    const file = await authFetch(pdfUrl);
    if (!file.ok) throw new Error(`PDF failed (${file.status})`);
    const blob = await file.blob();
    if (mine !== request.current) return;
    const blobUrl = URL.createObjectURL(blob);
    const zoom = view ? `&zoom=${view.zoom},${view.left},${view.top}` : '';
    // no thumbnail pane: more room for the page
    setPdf({ blobUrl, url: `${blobUrl}#page=${page}${zoom}&navpanes=0`, page, note });
  };

  // Runs one open request: the latest click wins, the button of `chunkId` waits meanwhile
  const run = async (chunkId: string, work: (mine: number) => Promise<void>) => {
    const mine = ++request.current;
    setLoading(chunkId);
    setStatus(null);
    setError(null);
    setNotFound(null);
    try {
      await work(mine);
    } catch (exc) {
      if (mine === request.current) setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      if (mine === request.current) {
        setLoading(null);
        setStatus(null);
      }
    }
  };

  const openFromStart = (chunkId: string, pdfUrl: string) => run(chunkId, (mine) =>
    showPdf(pdfUrl, 1, null, t('source.openedFromStart'), mine));

  const open = (chunk: CitedChunk) => run(chunk.chunk_id, async (mine) => {
    // First ask without downloading: an install without the crawled PDFs (corpus on Neon) fetches the PDF from
    // the kommun's site, which can take seconds, so the viewer says so before the download starts
    let location = await locateChunk(chunk.chunk_id, false);
    if (mine !== request.current) return;
    if (location.needs_download) {
      setStatus(fill(t('source.downloading'), { host: location.source_host ?? t('source.kommunWebsite') }));
      location = await locateChunk(chunk.chunk_id);
      if (mine !== request.current) return;
    }
    if (location.type === 'pdf' && location.pdf_url && location.found === false) {
      // Page 1 holds nothing the citation points at: say so, and open the PDF only when asked
      setNotFound({ chunkId: chunk.chunk_id, pdfUrl: location.pdf_url });
    } else if (location.type === 'pdf' && location.pdf_url) {
      const page = location.page ?? 1;
      await showPdf(location.pdf_url, page, location.view ?? null,
        fill(t(location.highlighted ? 'source.pageHighlighted' : 'source.pageNoHighlight'), { page: String(page) }), mine);
    } else if (location.type === 'url' && location.url) {
      window.open(location.url, '_blank', 'noopener,noreferrer');
    } else {
      setError(t('source.noOriginalDocument'));
    }
  });

  useEffect(() => {
    if (autoOpen && citation.chunks.length > 0) open(citation.chunks[0]);
  }, [citation, autoOpen]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <aside
        className={`flex h-full w-full flex-col bg-white shadow-xl dark:bg-zinc-900 ${pdf ? 'max-w-6xl' : 'max-w-xl'}`}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-start gap-3 border-b border-zinc-200 px-5 py-4 dark:border-zinc-700">
          {citation.n > 0 && (
            <span className="mt-0.5 rounded-md bg-blue-100 px-2 py-0.5 text-xs font-semibold text-blue-700 dark:bg-blue-950 dark:text-blue-300">
              {citation.n}
            </span>
          )}
          <h2 className="min-w-0 flex-1 text-sm font-semibold text-zinc-800 dark:text-zinc-100">{citation.label}</h2>
          <button onClick={onClose} className="rounded-lg p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800" title={t('source.close')}>
            <X size={16} />
          </button>
        </header>

        <div className={`flex min-h-0 flex-1 ${pdf ? 'flex-row' : 'flex-col'}`}>
          <div className={`space-y-3 overflow-y-auto px-5 py-4 ${pdf ? 'w-72 shrink-0 border-r border-zinc-200 dark:border-zinc-700' : ''}`}>
            {citation.chunks.map((chunk) => (
              <div key={chunk.chunk_id} className="space-y-1.5">
                <ChunkCard source={chunk.source} chunkIndex={chunk.chunk_index} content={chunk.content} defaultOpen={!pdf}
                  underline={supporting[chunk.chunk_id]} />
                {hasOriginal(chunk) ? (
                  // Only this button waits: another chunk can still be opened (the latest click wins)
                  <button
                    onClick={() => open(chunk)}
                    disabled={loading === chunk.chunk_id}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 px-2.5 py-1 text-xs text-zinc-600 hover:border-zinc-400 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300"
                  >
                    {loading === chunk.chunk_id ? <Loader2 size={12} className="animate-spin" /> :
                      chunk.doc_id?.startsWith('pdf:') ? <FileText size={12} /> : <ExternalLink size={12} />}
                    {chunk.doc_id?.startsWith('pdf:') ? t('source.openPdf') : t('source.openOriginal')}
                  </button>
                ) : (
                  <p className="text-xs italic text-zinc-500 dark:text-zinc-400">
                    {t('source.noOriginalKept')}
                  </p>
                )}
                {chunk.url && chunk.doc_id?.startsWith('pdf:') && (
                  <a
                    href={chunk.url}
                    target="_blank"
                    rel="noreferrer"
                    title={chunk.url}
                    className="ml-1.5 inline-flex items-center gap-1 text-xs text-blue-600 hover:underline dark:text-blue-400"
                  >
                    <ExternalLink size={12} /> <WithKommun text={t('source.onKommunWebsite')} />
                  </a>
                )}
                {notFound?.chunkId === chunk.chunk_id && (
                  <div role="alert" className="space-y-1.5 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
                    <p>{t('source.passageNotFound')}</p>
                    <button
                      onClick={() => openFromStart(notFound.chunkId, notFound.pdfUrl)}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 px-2.5 py-1 hover:border-amber-500 dark:border-amber-700"
                    >
                      <FileText size={12} /> {t('source.openFromPage1')}
                    </button>
                  </div>
                )}
                {loading === chunk.chunk_id && status && (
                  <p role="status" className="text-xs text-zinc-500 dark:text-zinc-400">{status}</p>
                )}
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
