'use client';

import { FormEvent, useEffect, useState } from 'react';
import { ArrowLeft, Loader2, Search } from 'lucide-react';
import { authFetch } from '@/lib/auth';
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
    note: 'data/corpus/chunks.jsonl, indexed chunks only',
  },
};

interface SourceCount {
  name: string;
  count: number;
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
}

interface ChunkPage {
  total: number;
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

function chunkMeta(row: ChunkRow): string[] {
  const meta: string[] = [];
  if (row.chapter) meta.push(`kap. ${row.chapter}${row.chapter_title ? ` — ${row.chapter_title}` : ''}`);
  if (row.section) meta.push(row.section.includes("§") ? row.section : `§ ${row.section}`);
  if (!row.has_embedding) meta.push('no embedding');
  return meta;
}

function StatCard({ label, overview }: { label: string; overview?: TableOverview }) {
  return (
    <div className="rounded-xl border border-zinc-200 px-4 py-3 dark:border-zinc-700">
      <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">{label}</div>
      {overview ? (
        <div className="mt-1 text-sm">
          <span className="text-xl font-semibold">{overview.total}</span> chunks
          <span className="text-zinc-500"> · {overview.sources.length} sources · {overview.with_embedding} embedded</span>
        </div>
      ) : (
        <Loader2 size={14} className="mt-2 animate-spin text-zinc-400" />
      )}
    </div>
  );
}

function ChunkTableView({ table, sources, store }: { table: TableName; sources: SourceCount[]; store: Store }) {
  const [source, setSource] = useState('');
  const [textInput, setTextInput] = useState('');
  const [text, setText] = useState('');
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<ChunkPage | null>(null);
  const [loadedQuery, setLoadedQuery] = useState('');
  const [error, setError] = useState('');

  const params = new URLSearchParams({ table, store, offset: String(offset), limit: String(PAGE_SIZE) });
  if (source) params.set('source', source);
  if (text) params.set('q', text);
  const query = params.toString();
  const loading = loadedQuery !== query;

  useEffect(() => {
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
  }, [query]);

  const applyFilter = (e: FormEvent) => {
    e.preventDefault();
    setOffset(0);
    setText(textInput.trim());
  };

  const total = page?.total ?? 0;

  return (
    <div className="space-y-3">
      <form onSubmit={applyFilter} className="flex flex-wrap gap-2">
        <select
          value={source}
          onChange={(e) => {
            setSource(e.target.value);
            setOffset(0);
          }}
          className="min-w-0 max-w-full flex-1 rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
        >
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s.name} value={s.name}>
              {s.name} ({s.count})
            </option>
          ))}
        </select>
        <input
          type="text"
          value={textInput}
          onChange={(e) => setTextInput(e.target.value)}
          placeholder="Filter by text (exact match)"
          className="min-w-0 flex-1 rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800"
        />
        <button
          type="submit"
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          Filter
        </button>
      </form>

      <div className="flex items-center justify-between text-xs text-zinc-500">
        <span>
          {loading ? 'Loading…' : total === 0 ? 'No chunks' : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} of ${total}`}
        </span>
        <div className="flex gap-2">
          <button
            disabled={offset === 0 || loading}
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            className="rounded-lg border border-zinc-300 px-3 py-1 disabled:opacity-40 dark:border-zinc-700"
          >
            Previous
          </button>
          <button
            disabled={offset + PAGE_SIZE >= total || loading}
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
            meta={chunkMeta(row)}
          />
        ))}
      </div>
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
            <StatCard label={labels.law} overview={currentOverview?.law} />
            <StatCard label={labels.document} overview={currentOverview?.document} />
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
