'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';
import { ArrowLeft, CheckCircle2, ChevronDown, ChevronRight, Loader2, Play, Search, XCircle } from 'lucide-react';
import { authFetch } from '@/lib/auth';
import CitedMarkdown from '@/components/CitedMarkdown';
import SourceViewer, { type Citation } from '@/components/SourceViewer';

// Benchmark view: browse the case sets used to evaluate the agent (backend/routers/benchmark.py), see how past
// benchmark runs answered each case, and run the agent on a case now (graded by the same LLM judge).

interface CaseSet { set: string; title: string; description: string; cases: number }
interface CaseRow { id: string; question: string; task?: string; verdicts: string[]; source?: string; has_image: boolean }
interface Evidence { law?: string; section?: string; contains?: string; title?: string; kommun_code?: string; doc_id?: string; any?: Evidence[] }
interface CaseDetail {
  id: string; question: string; task?: string; verdicts?: string[]; key_points: string[]; evidence: Evidence[];
  anchors?: { name: string; aliases?: string[] }[]; min_anchors?: number;
  source?: string; outcome?: string; url?: string; image?: string; label_explanation?: string;
}
// Task-specific scores of a graded answer (agentic/bench.py grade_answer); verdict_ok is null without accepted verdicts
interface TaskScores {
  task?: string; mode?: string | null; mode_ok?: boolean | null; anchors?: number; anchors_hit?: string[];
  proposals?: number; proposals_sourced?: number | null;
  points_obstacle?: number | null; points_lever?: number | null; points_ask?: number | null;
}
interface PastResult extends TaskScores {
  run: string; config: string; verdict: string; verdict_ok: boolean | null; points: number; evidence: number | null;
  grounded: number | null; tool_calls: number; map_views?: number; seconds: number; cost: number; comment?: string;
  answer?: string;
}
interface RunResult extends TaskScores {
  answer: string; citations: Citation[]; verdict: string; verdict_ok: boolean | null; points: number;
  point_scores?: number[]; comment?: string; evidence: number | null; map_views: number; tool_calls: number;
  llm_calls: number; seconds: number; cost: number;
}
interface Job { status: 'running' | 'done' | 'error'; progress: string[]; elapsed: number; result?: RunResult; error?: string }

const VERDICT_LABELS: Record<string, string> = {
  feasible: 'Feasible', conditional: 'With conditions', not_feasible: 'Not feasible', unclear: 'Unclear', none: 'No answer',
};

function fmt(value: number | null | undefined, digits = 2) {
  return value === null || value === undefined ? '–' : value.toFixed(digits);
}

function evidenceText(e: Evidence): string {
  if (e.any) return e.any.map(evidenceText).join(' or ');
  if (e.doc_id) return `the plan map (${e.doc_id})`;
  const where = e.law ? `${e.law}${e.section ? ` ${e.section}` : ''}` : e.kommun_code ? `kommun ${e.kommun_code}${e.title ? ` – ${e.title}` : ''}` : e.title ?? '';
  return e.contains ? `${where}: “${e.contains}”` : where;
}

const TASK_LABELS: Record<string, string> = {
  verdict: 'Verdict', explain: 'Explain', propose: 'Propose', develop: 'Develop',
};

function TaskBadge({ task, ok }: { task: string; ok?: boolean | null }) {
  const tone = ok === undefined || ok === null
    ? 'bg-violet-100 text-violet-700 dark:bg-violet-950/60 dark:text-violet-300'
    : ok ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300'
      : 'bg-red-100 text-red-700 dark:bg-red-950/60 dark:text-red-300';
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${tone}`}>{TASK_LABELS[task] ?? task}</span>;
}

// The scores beyond key points / evidence: anchors and proposals (propose), points per kind (develop)
function taskScores(r: TaskScores): string {
  const parts: string[] = [];
  if (r.anchors != null) parts.push(`places ${fmt(r.anchors)}${r.anchors_hit?.length ? ` (${r.anchors_hit.join(', ')})` : ''}`);
  if (r.proposals != null) parts.push(`${r.proposals} options, ${fmt(r.proposals_sourced)} sourced`);
  if (r.points_obstacle != null) parts.push(`obstacles ${fmt(r.points_obstacle)} · levers ${fmt(r.points_lever)} · asks ${fmt(r.points_ask)}`);
  return parts.map((part) => ` · ${part}`).join('');
}

// Badge of a graded answer: the verdict when the case has accepted verdicts, else the mode the agent chose
function ResultBadge({ r }: { r: PastResult | RunResult }) {
  if (r.verdict_ok !== null && r.verdict_ok !== undefined) return <VerdictBadge verdict={r.verdict} ok={r.verdict_ok} />;
  return <TaskBadge task={r.mode ?? r.task ?? '?'} ok={r.mode ? r.mode_ok : undefined} />;
}

function VerdictBadge({ verdict, ok }: { verdict: string; ok?: boolean }) {
  const tone = ok === undefined
    ? 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300'
    : ok ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300'
      : 'bg-red-100 text-red-700 dark:bg-red-950/60 dark:text-red-300';
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${tone}`}>{VERDICT_LABELS[verdict] ?? verdict}</span>;
}

function CaseImage({ caseId }: { caseId: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let objectUrl: string | null = null;
    authFetch(`/api/benchmark/image/${encodeURIComponent(caseId)}`)
      .then((response) => (response.ok ? response.blob() : null))
      .then((blob) => { if (blob) { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl); } });
    return () => { if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [caseId]);
  return url ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={url} alt="Plan map around the property" className="max-h-96 rounded-lg border border-zinc-200 dark:border-zinc-700" />
  ) : null;
}

function PastResults({ results }: { results: PastResult[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (results.length === 0) return <p className="text-xs italic text-zinc-500">This case has not been run in a benchmark yet.</p>;
  return (
    <div className="space-y-1">
      {results.map((r, i) => (
        <div key={`${r.run}-${i}`} className="rounded-lg border border-zinc-200 dark:border-zinc-700">
          <button onClick={() => setOpen(open === i ? null : i)} className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs">
            {open === i ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            <ResultBadge r={r} />
            <span className="min-w-0 flex-1 truncate text-zinc-700 dark:text-zinc-300">{r.config}</span>
            <span className="text-zinc-500">points {fmt(r.points)} · evidence {fmt(r.evidence)}{taskScores(r)}{r.map_views ? ` · ${r.map_views} map views` : ''} · {Math.round(r.seconds)} s · ${fmt(r.cost, 4)}</span>
          </button>
          {open === i && (
            <div className="space-y-2 border-t border-zinc-200 px-3 py-2 text-xs dark:border-zinc-700">
              {r.comment && <p className="italic text-zinc-600 dark:text-zinc-400">Judge: {r.comment}</p>}
              {r.answer && <pre className="max-h-80 overflow-auto whitespace-pre-wrap font-sans text-zinc-700 dark:text-zinc-300">{r.answer}</pre>}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function RunPanel({ set, caseId }: { set: string; caseId: string }) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openCitation, setOpenCitation] = useState<Citation | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  // The job shown: a poll answered after the user moved to another case must not show its result there
  const jobId = useRef<string | null>(null);

  // Remounted for each case (key): a new case starts with no job, and leaving one stops its polling
  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

  const start = async () => {
    setError(null);
    const response = await authFetch('/api/benchmark/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ set, id: caseId }),
    });
    if (!response.ok) { setError(`Could not start (${response.status})`); return; }
    const { job_id } = await response.json();
    jobId.current = job_id;
    setJob({ status: 'running', progress: [], elapsed: 0 });
    timer.current = setInterval(async () => {
      const poll = await authFetch(`/api/benchmark/run/${job_id}`);
      if (jobId.current !== job_id) return;
      if (!poll.ok) { setError(`Lost the run (${poll.status})`); if (timer.current) clearInterval(timer.current); return; }
      const next: Job = await poll.json();
      if (jobId.current !== job_id) return;
      setJob(next);
      if (next.status !== 'running' && timer.current) clearInterval(timer.current);
    }, 2000);
  };

  const result = job?.result;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <button
          onClick={start}
          disabled={job?.status === 'running'}
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {job?.status === 'running' ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
          {job?.status === 'running' ? `Running… ${job.elapsed} s` : 'Test with the agent'}
        </button>
        <span className="text-xs text-zinc-500">Same settings as the chat, graded by the benchmark judge (~$0.01 per run).</span>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
      {job && job.progress.length > 0 && !result && (
        <ul className="max-h-48 space-y-0.5 overflow-auto rounded-lg bg-zinc-50 p-2 font-mono text-[11px] text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
          {job.progress.map((line, i) => <li key={i}>{line}</li>)}
        </ul>
      )}
      {job?.status === 'error' && <p className="text-xs text-red-600">Run failed: {job.error}</p>}
      {result && (
        <div className="space-y-3 rounded-xl border border-zinc-200 p-4 dark:border-zinc-700">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {result.verdict_ok !== null && result.verdict_ok !== undefined && (result.verdict_ok
              ? <CheckCircle2 size={16} className="text-emerald-600" /> : <XCircle size={16} className="text-red-600" />)}
            <ResultBadge r={result} />
            <span className="text-zinc-600 dark:text-zinc-400">
              key points {fmt(result.points)} · evidence {fmt(result.evidence)}{taskScores(result)} · {result.tool_calls} tool calls
              {result.map_views ? ` · ${result.map_views} map views` : ''} · {Math.round(result.seconds)} s · ${fmt(result.cost, 4)}
            </span>
          </div>
          {result.comment && <p className="text-xs italic text-zinc-600 dark:text-zinc-400">Judge: {result.comment}</p>}
          <div className="prose prose-sm max-w-none text-sm dark:prose-invert">
            <CitedMarkdown body={result.answer} citations={result.citations} onOpen={setOpenCitation} />
          </div>
        </div>
      )}
      {openCitation && <SourceViewer citation={openCitation} onClose={() => setOpenCitation(null)} />}
    </div>
  );
}

export default function BenchmarkBrowser({ onBack }: { onBack: () => void }) {
  const [sets, setSets] = useState<CaseSet[]>([]);
  const [current, setCurrent] = useState<string>('cases');
  const [query, setQuery] = useState('');
  const [rows, setRows] = useState<CaseRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  // The case whose detail is shown: a slower answer for a previously clicked case must not replace it
  const selectedRef = useRef<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ case: CaseDetail; results: PastResult[] } | null>(null);

  useEffect(() => {
    authFetch('/api/benchmark/sets').then((r) => (r.ok ? r.json() : [])).then(setSets);
  }, []);

  const fetchCases = (set: string, q: string) => {
    const params = new URLSearchParams({ set, limit: '200', ...(q ? { q } : {}) });
    authFetch(`/api/benchmark/cases?${params}`)
      .then((r) => (r.ok ? r.json() : { items: [], total: 0 }))
      .then((page) => { setRows(page.items); setTotal(page.total); })
      .finally(() => setLoading(false));
  };
  const loadCases = (set: string, q: string) => { setLoading(true); fetchCases(set, q); };

  useEffect(() => { fetchCases('cases', ''); }, []);

  const selectSet = (set: string) => {
    setCurrent(set); setQuery(''); setSelected(null); setDetail(null); selectedRef.current = null;
    loadCases(set, '');
  };

  const selectCase = (id: string) => {
    setSelected(id); setDetail(null); selectedRef.current = id;
    authFetch(`/api/benchmark/case?set=${encodeURIComponent(current)}&id=${encodeURIComponent(id)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((detail) => { if (selectedRef.current === id) setDetail(detail); });
  };

  const onSearch = (event: FormEvent) => { event.preventDefault(); loadCases(current, query); };
  const currentSet = sets.find((s) => s.set === current);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
        <button onClick={onBack} className="rounded-lg p-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-800" title="Back to chat">
          <ArrowLeft size={18} />
        </button>
        <h1 className="text-lg font-semibold">Benchmark</h1>
        <div className="ml-4 flex gap-1">
          {sets.map((s) => (
            <button
              key={s.set}
              onClick={() => selectSet(s.set)}
              className={`rounded-lg px-3 py-1.5 text-sm ${current === s.set ? 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300' : 'hover:bg-zinc-100 dark:hover:bg-zinc-800'}`}
            >
              {s.title} <span className="opacity-60">({s.cases})</span>
            </button>
          ))}
        </div>
      </header>
      {currentSet && <p className="px-6 pt-3 text-xs text-zinc-500">{currentSet.description}</p>}
      <div className="flex min-h-0 flex-1 gap-4 px-6 py-3">
        <div className="flex w-96 shrink-0 flex-col">
          <form onSubmit={onSearch} className="mb-2 flex gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter cases (word, kommun, law…)"
              className="min-w-0 flex-1 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            />
            <button className="rounded-lg border border-zinc-200 px-2 dark:border-zinc-700" title="Filter"><Search size={14} /></button>
          </form>
          <p className="mb-1 text-xs text-zinc-500">{loading ? 'Loading…' : `${total} cases`}</p>
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
            {rows.map((row) => (
              <button
                key={row.id}
                onClick={() => selectCase(row.id)}
                className={`w-full rounded-lg border px-3 py-2 text-left text-xs ${selected === row.id ? 'border-blue-400 bg-blue-50 dark:border-blue-700 dark:bg-blue-950/40' : 'border-zinc-200 hover:border-zinc-400 dark:border-zinc-700'}`}
              >
                <div className="mb-1 flex items-center gap-1.5">
                  <span className="font-mono text-[10px] text-zinc-500">{row.id}</span>
                  {row.task && row.task !== 'verdict' && <TaskBadge task={row.task} />}
                  {row.verdicts.map((v) => <VerdictBadge key={v} verdict={v} />)}
                </div>
                <p className="line-clamp-2 text-zinc-700 dark:text-zinc-300">{row.question}</p>
              </button>
            ))}
          </div>
        </div>
        <div className="min-w-0 flex-1 overflow-y-auto">
          {!selected && <p className="pt-10 text-center text-sm text-zinc-500">Select a case to see its reference, past results, and test it.</p>}
          {selected && !detail && <Loader2 size={18} className="mx-auto mt-10 animate-spin text-zinc-400" />}
          {detail && (
            <div className="space-y-5 pb-10">
              <section className="space-y-2">
                <p className="font-mono text-xs text-zinc-500">{detail.case.id}</p>
                <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{detail.case.question}</p>
                {detail.case.image && <CaseImage caseId={detail.case.id} />}
              </section>
              <section className="space-y-2 rounded-xl bg-zinc-50 p-4 text-sm dark:bg-zinc-900">
                <div className="flex flex-wrap items-center gap-2">
                  <b className="text-xs">Task</b><TaskBadge task={detail.case.task ?? 'verdict'} />
                  {detail.case.verdicts?.length ? <><b className="ml-2 text-xs">Accepted verdicts</b>{detail.case.verdicts.map((v) => <VerdictBadge key={v} verdict={v} />)}</> : null}
                </div>
                {detail.case.anchors?.length ? (
                  <p className="text-xs text-zinc-700 dark:text-zinc-300">
                    <b>Places the plans designate</b> (the answer should name at least {detail.case.min_anchors ?? detail.case.anchors.length}): {detail.case.anchors.map((a) => a.name).join(', ')}
                  </p>
                ) : null}
                <div><b className="text-xs">Expected key points</b>
                  <ul className="ml-4 list-disc text-xs text-zinc-700 dark:text-zinc-300">{detail.case.key_points.map((p, i) => <li key={i}>{p}</li>)}</ul>
                </div>
                {detail.case.evidence.length > 0 && (
                  <div><b className="text-xs">Expected evidence (must be seen by the agent)</b>
                    <ul className="ml-4 list-disc text-xs text-zinc-700 dark:text-zinc-300">{detail.case.evidence.map((e, i) => <li key={i}>{evidenceText(e)}</li>)}</ul>
                  </div>
                )}
                {(detail.case.source || detail.case.outcome) && (
                  <p className="text-xs text-zinc-600 dark:text-zinc-400">
                    <b>Source</b>: {detail.case.url ? <a href={detail.case.url} target="_blank" rel="noopener noreferrer" className="underline">{detail.case.source}</a> : detail.case.source}
                    {detail.case.outcome ? ` – actual outcome: ${detail.case.outcome}` : ''}
                  </p>
                )}
                {detail.case.label_explanation && <p className="text-xs italic text-zinc-500">Reference reading of the map: {detail.case.label_explanation}</p>}
              </section>
              <section className="space-y-2">
                <h2 className="text-sm font-semibold">Test it now</h2>
                <RunPanel key={`${current}:${detail.case.id}`} set={current} caseId={detail.case.id} />
              </section>
              <section className="space-y-2">
                <h2 className="text-sm font-semibold">Past benchmark results ({detail.results.length})</h2>
                <PastResults results={detail.results} />
              </section>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
