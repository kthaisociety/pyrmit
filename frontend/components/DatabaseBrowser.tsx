'use client';

import { FormEvent, useEffect, useState } from 'react';
import { ArrowLeft, ChevronDown, ChevronRight, Loader2, Search } from 'lucide-react';
import { authFetch } from '@/lib/auth';
import { DOC_TYPE_LABELS, docTypeName, formatNumber } from '@/lib/corpus';
import ChunkCard from '@/components/ChunkCard';

type TableName = 'law' | 'document';
type Tab = TableName | 'search';
// neon: pgvector tables used by RETRIEVAL_BACKEND=pgvector; local: offline corpus (RETRIEVAL_BACKEND=local)
type Store = 'neon' | 'local';

const STORE_LABELS: Record<Store, { name: string; law: string; document: string; note: string }> = {
  neon: { name: 'Neon (pgvector)', law: 'law_chunks', document: 'document_chunks', note: 'RAG chunk tables' },
  local: {
    name: 'Local corpus',
    law: 'Laws (Riksdagen)',
    document: 'Kommun pages & PDFs',
    note: 'disk store data/index/store/<model> (SQLite + vectors)',
  },
};

interface TypeCount {
  doc_type: string;
  documents: number;
  chunks: number;
  pdfs: number;
  pages: number;
}

interface SourceCount {
  name: string;
  count: number;
  key?: string | null; // local corpus: kommun code (the filter value)
  documents?: number | null;
  types?: TypeCount[] | null;
}

interface TableOverview {
  total: number;
  with_embedding: number;
  sources: SourceCount[];
}

interface Overview {
  law: TableOverview;
  document: TableOverview;
}

interface ChunkRow {
  id: string;
  source: string;
  chunk_index: number | null;
  chapter: string | null;
  chapter_title: string | null;
  section: string | null;
  content: string;
  has_embedding: boolean;
  doc_id?: string | null;
  kind?: string | null;
  doc_type?: string | null;
  kommun?: string | null;
}

interface ChunkPage {
  total: number | null; // null: not counted (text filter over every kommun)
  has_more?: boolean | null;
  offset: number;
  limit: number;
  items: ChunkRow[];
}

interface SearchMatch {
  source: string;
  chunk_index: number | null;
  distance: number | null;
  content: string;
}

interface SearchResponse {
  embedding_ok: boolean;
  kommuner?: string[];
  law: SearchMatch[];
  document: SearchMatch[];
}

const PAGE_SIZE = 25;

const TAB_LABELS: Record<Tab, string> = {
  law: 'Law chunks',
  document: 'Document chunks',
  search: 'Semantic search',
};

function chunkMeta(row: ChunkRow, showKommun: boolean): string[] {
  const meta: string[] = [];
  if (row.chapter) meta.push(`kap. ${row.chapter}${row.chapter_title ? ` — ${row.chapter_title}` : ''}`);
  const lawSection = !row.kind || row.kind === 'law';
  if (row.section && lawSection) meta.push(row.section.includes('§') ? row.section : `§ ${row.section}`);
  if (showKommun && row.kommun) meta.push(row.kommun);
  if (row.doc_type) meta.push(docTypeName(row.doc_type));
  if (row.kind === 'pdf' || row.kind === 'page') meta.push(row.kind === 'pdf' ? 'PDF' : 'web page');
  if (!row.has_embedding) meta.push('no embedding');
  return meta;
}

function StatCard({ label, overview, unit }: { label: string; overview?: TableOverview; unit: string }) {
  const documents = overview?.sources.reduce((sum, s) => sum + (s.documents ?? 0), 0) ?? 0;
  return (
    <div className="rounded-xl border border-zinc-200 px-4 py-3 dark:border-zinc-700">
      <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">{label}</div>
      {overview ? (
        <div className="mt-1 text-sm">
          {documents > 0 && (
            <>
              <span className="text-xl font-semibold">{formatNumber(documents)}</span> documents
              <span className="text-zinc-400"> · </span>
            </>
          )}
          <span className={documents > 0 ? 'font-medium' : 'text-xl font-semibold'}>{formatNumber(overview.total)}</span> chunks
          <span className="text-zinc-500"> · {formatNumber(overview.sources.length)} {unit}</span>
          {overview.with_embedding !== overview.total && (
            <span className="text-zinc-500"> · {formatNumber(overview.with_embedding)} embedded</span>
          )}
        </div>
      ) : (
        <Loader2 size={14} className="mt-2 animate-spin text-zinc-400" />
      )}
    </div>
  );
}

/** Document types of the selected kommun (or of every kommun), as filter chips with their document counts. */
function TypeChips({ types, value, onChange }: { types: TypeCount[]; value: string; onChange: (v: string) => void }) {
  const total = types.reduce((sum, t) => sum + t.documents, 0);
  const chip = (key: string, label: string, count: number, title: string) => (
    <button
      key={key}
      type="button"
      title={title}
      onClick={() => onChange(key)}
      className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
        value === key
          ? 'border-blue-600 bg-blue-600 text-white'
          : 'border-zinc-300 text-zinc-600 hover:border-zinc-400 dark:border-zinc-700 dark:text-zinc-300'
      }`}
    >
      {label} <span className={value === key ? 'text-blue-100' : 'text-zinc-400'}>{formatNumber(count)}</span>
    </button>
  );
  return (
    <div className="flex flex-wrap gap-1.5">
      {chip('', 'All types', total, 'every document type')}
      {types.map((t) =>
        chip(
          t.doc_type,
          docTypeName(t.doc_type),
          t.documents,
          `${DOC_TYPE_LABELS[t.doc_type]?.hint ?? t.doc_type}\n${formatNumber(t.pdfs)} PDFs, ${formatNumber(t.pages)} web pages, ${formatNumber(t.chunks)} chunks`,
        ),
      )}
    </div>
  );
}

interface DocumentRow {
  doc_id: string;
  title: string;
  kind: string;
  doc_type: string | null;
  url: string | null;
  chunks: number;
}

interface DocumentPage {
  total: number;
  offset: number;
  limit: number;
  items: DocumentRow[];
}

const DOC_PAGE_SIZE = 50;

/** One document of a kommun: click to load its chunks. */
function DocumentItem({ doc }: { doc: DocumentRow }) {
  const [chunks, setChunks] = useState<ChunkRow[] | null>(null);
  const [open, setOpen] = useState(false);
  const toggle = () => {
    setOpen((o) => !o);
    if (!chunks) {
      authFetch(`/api/db/chunks?${new URLSearchParams({ table: 'document', store: 'local', doc_id: doc.doc_id, limit: '100' })}`)
        .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`Request failed: ${res.status}`))))
        .then((data: ChunkPage) => setChunks(data.items))
        .catch(() => setChunks([]));
    }
  };
  return (
    <div className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-950/70">
      <button onClick={toggle} className="flex w-full items-center gap-2 px-3 py-2 text-left">
        <span className="text-zinc-400">{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</span>
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-zinc-800 dark:text-zinc-100">{doc.title}</span>
        <span className="rounded-full bg-zinc-100 px-1.5 py-0.5 text-[11px] text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
          {doc.kind === 'pdf' ? 'PDF' : 'web page'}
        </span>
        <span className="w-20 text-right text-[11px] tabular-nums text-zinc-500">
          {formatNumber(doc.chunks)} chunk{doc.chunks === 1 ? '' : 's'}
        </span>
      </button>
      {open && (
        <div className="space-y-1.5 border-t border-zinc-200 px-3 py-2 dark:border-zinc-700">
          {doc.url && (
            <a href={doc.url} target="_blank" rel="noreferrer" className="block truncate text-[11px] text-blue-600 hover:underline dark:text-blue-400">
              {doc.url}
            </a>
          )}
          {!chunks && <Loader2 size={14} className="animate-spin text-zinc-400" />}
          {chunks?.map((row) => (
            <ChunkCard key={row.id} source={row.source} chunkIndex={row.chunk_index} content={row.content} meta={chunkMeta(row, false)} />
          ))}
          {chunks && doc.chunks > chunks.length && (
            <p className="text-[11px] text-zinc-500">First {chunks.length} of {formatNumber(doc.chunks)} chunks.</p>
          )}
        </div>
      )}
    </div>
  );
}

/** A kommun's documents, grouped by type (the order the backend sorts them in), 50 per page. */
function DocumentList({ source, docType, text }: { source: string; docType: string; text: string }) {
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<DocumentPage | null>(null);
  const [loadedQuery, setLoadedQuery] = useState('');
  const [error, setError] = useState('');
  const params = new URLSearchParams({ source, offset: String(offset), limit: String(DOC_PAGE_SIZE) });
  if (docType) params.set('doc_type', docType);
  if (text) params.set('q', text);
  const query = params.toString();
  const loading = loadedQuery !== query;

  useEffect(() => {
    authFetch(`/api/db/documents?${query}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`Request failed: ${res.status}`))))
      .then((data: DocumentPage) => {
        setPage(data);
        setError('');
      })
      .catch((err) => setError(String(err)))
      .finally(() => setLoadedQuery(query));
  }, [query]);

  const total = page?.total ?? 0;
  const items = page?.items ?? [];
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-xs text-zinc-500">
        <span>
          {loading
            ? 'Loading…'
            : total === 0
              ? 'No documents'
              : `Documents ${formatNumber(offset + 1)}–${formatNumber(offset + items.length)} of ${formatNumber(total)}${text ? ` with "${text}" in the title` : ''}`}
        </span>
        <div className="flex gap-2">
          <button
            disabled={offset === 0 || loading}
            onClick={() => setOffset((o) => Math.max(0, o - DOC_PAGE_SIZE))}
            className="rounded-lg border border-zinc-300 px-3 py-1 disabled:opacity-40 dark:border-zinc-700"
          >
            Previous
          </button>
          <button
            disabled={offset + DOC_PAGE_SIZE >= total || loading}
            onClick={() => setOffset((o) => o + DOC_PAGE_SIZE)}
            className="rounded-lg border border-zinc-300 px-3 py-1 disabled:opacity-40 dark:border-zinc-700"
          >
            Next
          </button>
        </div>
      </div>
      {error && <div className="text-sm text-red-500">{error}</div>}
      <div className="space-y-1.5">
        {items.map((doc, i) => (
          <div key={doc.doc_id} className="space-y-1.5">
            {(i === 0 || items[i - 1].doc_type !== doc.doc_type) && (
              <h3 className="pt-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">
                {docTypeName(doc.doc_type)}
                <span className="ml-2 font-normal normal-case tracking-normal text-zinc-400">
                  {DOC_TYPE_LABELS[doc.doc_type ?? 'other']?.hint}
                </span>
              </h3>
            )}
            <DocumentItem doc={doc} />
          </div>
        ))}
      </div>
    </div>
  );
}

function sumTypes(sources: SourceCount[]): TypeCount[] {
  const merged = new Map<string, TypeCount>();
  for (const source of sources) {
    for (const t of source.types ?? []) {
      const m = merged.get(t.doc_type) ?? { doc_type: t.doc_type, documents: 0, chunks: 0, pdfs: 0, pages: 0 };
      merged.set(t.doc_type, {
        ...m,
        documents: m.documents + t.documents,
        chunks: m.chunks + t.chunks,
        pdfs: m.pdfs + t.pdfs,
        pages: m.pages + t.pages,
      });
    }
  }
  const order = Object.keys(DOC_TYPE_LABELS);
  return [...merged.values()].sort((a, b) => order.indexOf(a.doc_type) - order.indexOf(b.doc_type));
}

function ChunkTableView({ table, sources, store }: { table: TableName; sources: SourceCount[]; store: Store }) {
  const [source, setSource] = useState('');
  const [docType, setDocType] = useState('');
  const [textInput, setTextInput] = useState('');
  const [text, setText] = useState('');
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<ChunkPage | null>(null);
  const [loadedQuery, setLoadedQuery] = useState('');
  const [error, setError] = useState('');
  const byKommun = sources.some((s) => s.types);
  const selected = sources.find((s) => (s.key ?? s.name) === source);
  const types = byKommun ? (selected ? selected.types ?? [] : sumTypes(sources)) : [];
  // A kommun is selected: list its documents (by type, then title) instead of its chunks
  const documentsMode = byKommun && Boolean(source);

  const params = new URLSearchParams({ table, store, offset: String(offset), limit: String(PAGE_SIZE) });
  if (source) params.set('source', source);
  if (docType) params.set('doc_type', docType);
  if (text) params.set('q', text);
  const query = params.toString();
  const loading = loadedQuery !== query;

  useEffect(() => {
    if (documentsMode) return;
    authFetch(`/api/db/chunks?${query}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Request failed: ${res.status}`);
        return res.json();
      })
      .then((data: ChunkPage) => {
        setPage(data);
        setError('');
      })
      .catch((err) => setError(String(err)))
      .finally(() => setLoadedQuery(query));
  }, [query, documentsMode]);

  const applyFilter = (e: FormEvent) => {
    e.preventDefault();
    setOffset(0);
    setText(textInput.trim());
  };

  const total = page?.total ?? null;
  const shown = page?.items.length ?? 0;
  const hasNext = total !== null ? offset + PAGE_SIZE < total : Boolean(page?.has_more);
  const range =
    shown === 0
      ? 'No chunks'
      : `${formatNumber(offset + 1)}–${formatNumber(offset + shown)} of ${total !== null ? formatNumber(total) : 'many (not counted over every kommun)'}`;

  return (
    <div className="space-y-3">
      <form onSubmit={applyFilter} className="flex flex-wrap gap-2">
        <select
          value={source}
          onChange={(e) => {
            setSource(e.target.value);
            setDocType('');
            setOffset(0);
          }}
          className="min-w-0 max-w-full flex-1 rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
        >
          <option value="">{byKommun ? `All kommuner (${formatNumber(sources.length)})` : 'All sources'}</option>
          {sources.map((s) => (
            <option key={s.key ?? s.name} value={s.key ?? s.name}>
              {s.name} ({s.documents != null ? `${formatNumber(s.documents)} documents` : `${formatNumber(s.count)} chunks`})
            </option>
          ))}
        </select>
        <input
          type="text"
          value={textInput}
          onChange={(e) => setTextInput(e.target.value)}
          placeholder={documentsMode ? 'Filter by document title' : 'Filter by text (exact match)'}
          className="min-w-0 flex-1 rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
        />
        <button
          type="submit"
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          Filter
        </button>
      </form>

      {byKommun && (
        <TypeChips
          types={types}
          value={docType}
          onChange={(value) => {
            setDocType(value);
            setOffset(0);
          }}
        />
      )}
      {byKommun && !source && (
        <p className="text-xs text-zinc-500">
          Pick a kommun to see its documents sorted by type. Without one, chunks come in the order the corpus stores
          them.
        </p>
      )}

      {documentsMode ? (
        <DocumentList key={`${source}-${docType}-${text}`} source={source} docType={docType} text={text} />
      ) : (
        <>
          <div className="flex items-center justify-between text-xs text-zinc-500">
            <span>{loading ? 'Loading…' : range}</span>
            <div className="flex gap-2">
              <button
                disabled={offset === 0 || loading}
                onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                className="rounded-lg border border-zinc-300 px-3 py-1 disabled:opacity-40 dark:border-zinc-700"
              >
                Previous
              </button>
              <button
                disabled={!hasNext || loading}
                onClick={() => setOffset((o) => o + PAGE_SIZE)}
                className="rounded-lg border border-zinc-300 px-3 py-1 disabled:opacity-40 dark:border-zinc-700"
              >
                Next
              </button>
            </div>
          </div>

          {error && <div className="text-sm text-red-500">{error}</div>}

          <div className="space-y-1.5">
            {page?.items.map((row) => (
              <ChunkCard
                key={row.id}
                source={row.source}
                chunkIndex={row.chunk_index}
                content={row.content}
                meta={chunkMeta(row, byKommun)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function SemanticSearchView({ store }: { store: Store }) {
  const [query, setQuery] = useState('');
  const [k, setK] = useState(5);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const runSearch = async (e: FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError('');
    try {
      const res = await authFetch('/api/db/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query.trim(), k, store }),
      });
      if (!res.ok) throw new Error(`Request failed: ${res.status}`);
      setResult(await res.json());
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  const sections: { label: string; matches: SearchMatch[] }[] = result
    ? [
        { label: 'Law chunks', matches: result.law },
        { label: 'Document chunks', matches: result.document },
      ]
    : [];

  return (
    <div className="space-y-4">
      <p className="text-xs text-zinc-500">
        {store === 'local'
          ? 'Runs the local retrieval (embeddings on the GPU, kommun filter from the place names in the query), without calling the LLM. Type the query in Swedish: the chat searches with the Swedish rewrite of your question.'
          : 'Runs the same embedding + cosine-distance retrieval as the chat, without calling the LLM. Tip: the chat searches with the English rewrite of your question (see the pipeline inspector).'}
      </p>
      <form onSubmit={runSearch} className="flex flex-wrap gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. maximum building height in detaljplan"
          className="min-w-0 flex-[3] rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
        />
        <label className="flex items-center gap-2 text-xs text-zinc-500">
          k
          <input
            type="number"
            min={1}
            max={50}
            value={k}
            onChange={(e) => setK(Math.min(50, Math.max(1, Number(e.target.value) || 1)))}
            className="w-16 rounded-lg border border-zinc-300 bg-white px-2 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
          />
        </label>
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-zinc-300 dark:disabled:bg-zinc-700"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
          Search
        </button>
      </form>

      {error && <div className="text-sm text-red-500">{error}</div>}
      {result?.kommuner !== undefined && store === 'local' && (
        <div className="text-xs text-zinc-500">
          Kommun filter: {result.kommuner.length > 0 ? result.kommuner.join(', ') : 'none detected (all kommuner)'}
        </div>
      )}
      {result && !result.embedding_ok && (
        <div className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-950/50 dark:text-red-300">
          Embedding failed — check OPENAI_API_KEY on the backend.
        </div>
      )}

      {sections.map(({ label, matches }) => (
        <div key={label} className="space-y-1.5">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-zinc-500">{label}</h3>
          {matches.length === 0 ? (
            <div className="text-xs italic text-zinc-500">No matches.</div>
          ) : (
            matches.map((match, i) => (
              <ChunkCard
                key={`${match.source}-${match.chunk_index}-${i}`}
                rank={i + 1}
                source={match.source}
                chunkIndex={match.chunk_index}
                distance={match.distance}
                content={match.content}
              />
            ))
          )}
        </div>
      ))}
    </div>
  );
}

export default function DatabaseBrowser({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState<Tab>('law');
  const [store, setStore] = useState<Store>('local');
  const [overview, setOverview] = useState<Overview | null>(null);
  const [loadedStore, setLoadedStore] = useState<Store | null>(null);
  const [error, setError] = useState('');
  const labels = STORE_LABELS[store];
  const currentOverview = loadedStore === store ? overview : null;

  useEffect(() => {
    authFetch(`/api/db/overview?store=${store}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Request failed: ${res.status}`);
        return res.json();
      })
      .then((data: Overview) => {
        setOverview(data);
        setError('');
      })
      .catch((err) => setError(String(err)))
      .finally(() => setLoadedStore(store));
  }, [store]);

  return (
    <div className="flex h-full w-full flex-col">
      <div className="flex items-center gap-3 border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
        <button
          onClick={onBack}
          className="rounded-lg p-1.5 transition-colors hover:bg-zinc-100 dark:hover:bg-zinc-800"
        >
          <ArrowLeft size={20} />
        </button>
        <h1 className="text-lg font-semibold">Database</h1>
        <span className="text-xs text-zinc-500">read-only · {labels.note}</span>
        <div className="ml-auto flex rounded-lg border border-zinc-300 p-0.5 text-xs dark:border-zinc-700">
          {(Object.keys(STORE_LABELS) as Store[]).map((key) => (
            <button
              key={key}
              onClick={() => setStore(key)}
              className={`rounded-md px-3 py-1 transition-colors ${
                store === key
                  ? 'bg-blue-600 font-medium text-white'
                  : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
              }`}
            >
              {STORE_LABELS[key].name}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl space-y-5 p-6">
          {error && <div className="text-sm text-red-500">{error}</div>}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <StatCard label={labels.law} overview={currentOverview?.law} unit="statutes" />
            <StatCard
              label={labels.document}
              overview={currentOverview?.document}
              unit={store === 'local' ? 'kommuner' : 'documents'}
            />
          </div>

          <div className="flex gap-1 border-b border-zinc-200 dark:border-zinc-800">
            {(Object.keys(TAB_LABELS) as Tab[]).map((key) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`-mb-px border-b-2 px-3 py-2 text-sm transition-colors ${
                  tab === key
                    ? 'border-blue-600 font-medium text-blue-600'
                    : 'border-transparent text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
                }`}
              >
                {key === 'search' ? TAB_LABELS.search : labels[key]}
              </button>
            ))}
          </div>

          {tab === 'search' ? (
            <SemanticSearchView key={store} store={store} />
          ) : (
            <ChunkTableView
              key={`${store}-${tab}`}
              table={tab}
              store={store}
              sources={currentOverview?.[tab].sources ?? []}
            />
          )}
        </div>
      </div>
    </div>
  );
}
