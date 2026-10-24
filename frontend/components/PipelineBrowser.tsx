'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Info,
  Loader2,
  RefreshCw,
  XCircle,
} from 'lucide-react';
import { authFetch } from '@/lib/auth';
import { compactNumber, formatNumber } from '@/lib/corpus';

// Pipeline view: how the searchable corpus is built and how well each step works, written for a reader without the
// project's context. Progressive: a strip of the steps, then one card per step (status + key numbers); opening a
// card explains what the step does and how it is measured, and each detail section opens on its own. Data from
// backend/routers/pipeline.py (the files the steps write). The Benchmark view grades the agent's answers instead.

type Cell = string | number | null;
type Level = 'good' | 'warning' | 'info';
interface Status { level: Level; label: string; note: string }
interface Tile { label: string; value: Cell; hint?: string }
interface Bar { label: string; value: number; hint?: string }
interface Table { columns: string[]; rows: Cell[][]; highlight?: number; limit?: number; search?: boolean }
interface CheckLine { section: string; level: 'OK' | 'WARN' | 'ERROR' | 'INFO'; message: string; examples: string[]; count: number }
interface Section {
  title: string;
  summary: string;
  text?: string;
  table?: Table;
  bars?: Bar[];
  meter?: { value: number; total: number; label: string };
  checks?: CheckLine[];
  examples?: string[];
}
interface Step {
  id: string;
  step: number;
  title: string;
  what: string;
  measure: string;
  status: Status;
  flow: { value: number | string | null; caption: string } | null;
  tiles: Tile[];
  sections: Section[];
}

const GLOSSARY: [string, string][] = [
  ['Kommun', "Sweden's 290 municipalities. Each one decides its own plans and building permits."],
  ['Detaljplan', 'Legally binding plan for an area: what may be built there, how high, how large, for what use.'],
  ['Plankarta', 'The map of a detaljplan: zones marked with codes (e1, h1...) whose rules are listed beside the map.'],
  ['Översiktsplan', "Non-binding plan for the whole kommun's development: where it intends to build."],
  ['Bygglov', 'Building permit, granted by the kommun.'],
  ['Crawl', "Automatic visit of a website's pages to collect them."],
  ['OCR', 'Optical character recognition: reading the text of a scanned page, which is only an image.'],
  ['Passage (chunk)', 'A piece of a document of about 1,500 characters. Search returns passages, not whole documents.'],
  ['Vector (embedding)', "A list of numbers that represents a passage's meaning: passages with close vectors talk about the same thing."],
  ['LLM', 'Large language model. MiMo Flash judges the PDFs in the filter; GPT-6 Luna is the agent that answers.'],
  ['Typical / slow time', 'Median (half of the calls are faster) and 95th percentile (95 % of the calls are faster).'],
];

const LEVEL_STYLE: Record<Level, { icon: typeof Info; className: string }> = {
  good: { icon: CheckCircle2, className: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300' },
  warning: { icon: AlertTriangle, className: 'bg-amber-50 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300' },
  info: { icon: Info, className: 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300' },
};

function show(value: Cell | undefined): string {
  if (value === null || value === undefined) return '–';
  return typeof value === 'number' ? formatNumber(value) : value;
}

function shortTitle(title: string): string {
  return title.split(':')[0];
}

function StatusPill({ status }: { status: Status }) {
  const { icon: Icon, className } = LEVEL_STYLE[status.level];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${className}`} title={status.note}>
      <Icon size={12} />
      {status.label}
    </span>
  );
}

function Tiles({ tiles }: { tiles: Tile[] }) {
  return (
    <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
      {tiles.map((tile) => (
        <div key={tile.label} className="rounded-lg bg-zinc-50 px-3 py-2 dark:bg-zinc-900">
          <p className="text-[11px] text-zinc-500">{tile.label}</p>
          <p className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">{show(tile.value)}</p>
          {tile.hint && <p className="text-[11px] leading-snug text-zinc-400">{tile.hint}</p>}
        </div>
      ))}
    </div>
  );
}

function Bars({ bars }: { bars: Bar[] }) {
  const max = Math.max(1, ...bars.map((b) => b.value));
  return (
    <div className="space-y-1">
      {bars.map((bar) => (
        <div
          key={bar.label}
          title={`${bar.label}: ${formatNumber(bar.value)}${bar.hint ? `\n${bar.hint}` : ''}`}
          className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)_4.5rem] items-center gap-3 rounded px-1 py-0.5 text-xs hover:bg-zinc-50 dark:hover:bg-zinc-900"
        >
          <span className="truncate text-zinc-700 dark:text-zinc-300">{bar.label}</span>
          <span className="h-2 rounded-full bg-zinc-100 dark:bg-zinc-800">
            <span className="block h-2 rounded-full bg-blue-500" style={{ width: `${Math.max(1, (100 * bar.value) / max)}%` }} />
          </span>
          <span className="text-right tabular-nums text-zinc-600 dark:text-zinc-400">{formatNumber(bar.value)}</span>
        </div>
      ))}
    </div>
  );
}

function DataTable({ table }: { table: Table }) {
  const [all, setAll] = useState(false);
  const [query, setQuery] = useState('');
  const rows = useMemo(
    () => (query ? table.rows.filter((row) => row.some((cell) => String(cell ?? '').toLowerCase().includes(query.toLowerCase()))) : table.rows),
    [table.rows, query],
  );
  const limit = table.limit && !all && !query ? table.limit : rows.length;
  // A column of numbers is right-aligned, header included
  const numeric = table.columns.map((_, j) => typeof table.rows.find((row) => row[j] !== null)?.[j] === 'number');
  if (table.rows.length === 0) return <p className="text-xs italic text-zinc-500">No measurement yet.</p>;
  return (
    <div className="space-y-2">
      {table.search && (
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter rows…"
          className="w-full max-w-xs rounded-lg border border-zinc-300 bg-white px-2.5 py-1 text-xs dark:border-zinc-700 dark:bg-zinc-800"
        />
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-zinc-200 text-left text-zinc-500 dark:border-zinc-700">
              {table.columns.map((c, j) => (
                <th key={c} className={`px-2 py-1 font-medium ${numeric[j] ? 'text-right' : ''}`}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, limit).map((row, i) => (
              <tr
                key={i}
                className={`border-b border-zinc-100 text-zinc-700 dark:border-zinc-800 dark:text-zinc-300 ${
                  !query && i === table.highlight ? 'bg-blue-50/60 font-medium dark:bg-blue-950/30' : ''
                }`}
              >
                {row.map((cell, j) => (
                  <td key={j} className={`px-2 py-1 ${typeof cell === 'number' ? 'text-right tabular-nums' : ''}`}>{show(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > limit && (
        <button onClick={() => setAll(true)} className="text-xs text-blue-600 hover:underline dark:text-blue-400">
          Show all {formatNumber(rows.length)} rows
        </button>
      )}
    </div>
  );
}

const CHECK_ICON = {
  OK: { icon: CheckCircle2, className: 'text-emerald-600', label: 'OK' },
  WARN: { icon: AlertTriangle, className: 'text-amber-600', label: 'Warning' },
  ERROR: { icon: XCircle, className: 'text-red-600', label: 'Error' },
  INFO: { icon: Info, className: 'text-zinc-500', label: 'Info' },
};

function Checks({ checks }: { checks: CheckLine[] }) {
  const [open, setOpen] = useState<number | null>(null);
  const [passed, setPassed] = useState(false);
  if (checks.length === 0) return <p className="text-xs italic text-zinc-500">The checks have not run on this corpus yet.</p>;
  const hidden = passed ? 0 : checks.filter((line) => line.level === 'OK').length;
  return (
    <ul className="space-y-0.5">
      {checks.map((line, i) => {
        if (line.level === 'OK' && !passed) return null;
        const { icon: Icon, className, label } = CHECK_ICON[line.level];
        const expandable = line.examples.length > 0;
        return (
          <li key={i}>
            <button
              disabled={!expandable}
              onClick={() => setOpen(open === i ? null : i)}
              className="flex w-full items-start gap-2 rounded px-1 py-0.5 text-left text-xs hover:bg-zinc-50 disabled:cursor-default disabled:hover:bg-transparent dark:hover:bg-zinc-900"
            >
              <Icon size={13} className={`mt-0.5 shrink-0 ${className}`} aria-label={label} />
              <span className="flex-1 text-zinc-700 dark:text-zinc-300">
                <span className="text-zinc-400">{line.section.split(' (')[0]} · </span>
                {line.message}
              </span>
              {expandable && (open === i ? <ChevronDown size={13} className="mt-0.5 text-zinc-400" /> : <ChevronRight size={13} className="mt-0.5 text-zinc-400" />)}
            </button>
            {open === i && (
              <ul className="mb-1 ml-6 space-y-0.5 border-l border-zinc-200 pl-3 text-[11px] text-zinc-500 dark:border-zinc-700">
                {line.examples.map((example) => <li key={example} className="break-all">{example}</li>)}
                {line.count > line.examples.length && <li>… and {formatNumber(line.count - line.examples.length)} more</li>}
              </ul>
            )}
          </li>
        );
      })}
      {hidden > 0 && (
        <li>
          <button onClick={() => setPassed(true)} className="px-1 text-xs text-blue-600 hover:underline dark:text-blue-400">
            Show the {hidden} checks that pass
          </button>
        </li>
      )}
    </ul>
  );
}

function SectionView({ section }: { section: Section }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-t border-zinc-100 dark:border-zinc-800">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-baseline gap-2 py-2 text-left">
        {open ? <ChevronDown size={14} className="shrink-0 self-center text-zinc-400" /> : <ChevronRight size={14} className="shrink-0 self-center text-zinc-400" />}
        <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{section.title}</span>
        {section.summary && <span className="truncate text-xs text-zinc-500">{section.summary}</span>}
      </button>
      {open && (
        <div className="space-y-3 pb-3 pl-6">
          {section.text && <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">{section.text}</p>}
          {section.meter && (
            <div>
              <div className="h-2.5 rounded-full bg-blue-100 dark:bg-blue-950">
                <div
                  className="h-2.5 rounded-full bg-blue-500"
                  style={{ width: `${Math.min(100, (100 * section.meter.value) / section.meter.total)}%` }}
                />
              </div>
              <p className="mt-1 text-xs text-zinc-500">
                {formatNumber(section.meter.value)} of {formatNumber(section.meter.total)} {section.meter.label} (
                {Math.round((100 * section.meter.value) / section.meter.total)} %)
              </p>
            </div>
          )}
          {section.bars && <Bars bars={section.bars} />}
          {section.table && <DataTable table={section.table} />}
          {section.checks && <Checks checks={section.checks} />}
          {section.examples && section.examples.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-4 text-xs text-zinc-600 dark:text-zinc-400">
              {section.examples.map((example) => <li key={example}>{example}</li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function StepCard({ step, open, onToggle }: { step: Step; open: boolean; onToggle: () => void }) {
  return (
    <section id={`step-${step.id}`} className="scroll-mt-4 rounded-xl border border-zinc-200 dark:border-zinc-800">
      <button onClick={onToggle} className="flex w-full items-center gap-3 px-4 pt-3 text-left">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-zinc-900 text-xs font-semibold text-white dark:bg-zinc-100 dark:text-zinc-900">
          {step.step}
        </span>
        <h2 className="flex-1 text-base font-semibold text-zinc-900 dark:text-zinc-100">{step.title}</h2>
        <StatusPill status={step.status} />
        {open ? <ChevronDown size={16} className="text-zinc-400" /> : <ChevronRight size={16} className="text-zinc-400" />}
      </button>
      <div className="space-y-3 px-4 pb-3 pt-2">
        {step.status.note && <p className="pl-9 text-xs text-zinc-500">{step.status.note}</p>}
        <Tiles tiles={step.tiles} />
        {open ? (
          <div className="space-y-3">
            <div className="grid gap-3 text-xs leading-relaxed text-zinc-600 dark:text-zinc-400 md:grid-cols-2">
              <div>
                <p className="mb-0.5 font-semibold text-zinc-800 dark:text-zinc-200">What this step does</p>
                <p>{step.what}</p>
              </div>
              <div>
                <p className="mb-0.5 font-semibold text-zinc-800 dark:text-zinc-200">How we measure it</p>
                <p>{step.measure}</p>
              </div>
            </div>
            <div>{step.sections.map((section) => <SectionView key={section.title} section={section} />)}</div>
          </div>
        ) : (
          <button onClick={onToggle} className="text-xs text-blue-600 hover:underline dark:text-blue-400">
            What it does, how it is measured, details ({step.sections.length} sections)
          </button>
        )}
      </div>
    </section>
  );
}

function FlowStrip({ steps, onSelect }: { steps: Step[]; onSelect: (id: string) => void }) {
  return (
    <ol className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
      {steps.map((step) => {
        const { icon: Icon, className } = LEVEL_STYLE[step.status.level];
        return (
          <li key={step.id}>
            <button
              onClick={() => onSelect(step.id)}
              className="flex h-full w-full flex-col rounded-lg border border-zinc-200 px-3 py-2 text-left transition-colors hover:border-blue-400 dark:border-zinc-800 dark:hover:border-blue-600"
            >
              <span className="flex items-center gap-1.5 text-[11px] text-zinc-500">
                <span className="font-semibold text-zinc-700 dark:text-zinc-300">{step.step}</span>
                {shortTitle(step.title)}
                <Icon size={12} className={`ml-auto rounded-full ${className}`} aria-label={step.status.label} />
              </span>
              <span
                className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-100"
                title={typeof step.flow?.value === 'number' ? formatNumber(step.flow.value) : undefined}
              >
                {typeof step.flow?.value === 'number'
                  ? `${step.flow.value < 0 ? '−' : ''}${compactNumber(Math.abs(step.flow.value))}`
                  : step.flow?.value ?? '–'}
              </span>
              <span className="text-[11px] leading-snug text-zinc-500">{step.flow?.caption}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

export default function PipelineBrowser({ onBack }: { onBack: () => void }) {
  const [steps, setSteps] = useState<Step[] | null>(null);
  const [corpus, setCorpus] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [glossary, setGlossary] = useState(false);

  const fetchSteps = () =>
    authFetch('/api/pipeline')
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`))))
      .then((data) => {
        setSteps(data.steps);
        setCorpus(data.corpus);
      })
      .catch((e) => setError(String(e)));
  useEffect(() => {
    fetchSteps();
  }, []);
  const reload = () => {
    setError(null);
    setSteps(null);
    fetchSteps();
  };
  const toggle = (id: string) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const select = (id: string) => {
    setOpen((current) => new Set(current).add(id));
    requestAnimationFrame(() => document.getElementById(`step-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
        <button onClick={onBack} className="rounded-lg p-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-800" title="Back to chat">
          <ArrowLeft size={18} />
        </button>
        <h1 className="text-lg font-semibold">Pipeline</h1>
        {corpus && <span className="text-xs text-zinc-500">corpus: {corpus}</span>}
        <button onClick={reload} className="ml-auto rounded-lg p-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-800" title="Reload">
          <RefreshCw size={16} />
        </button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-5xl space-y-4 px-6 py-5 pb-12">
          <div className="space-y-1.5">
            <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">How the corpus is built</h2>
            <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
              Pyrmit answers questions about building in Sweden from two sources: the national laws, and the documents
              each kommun publishes (plans, permit guidance, fees). This page follows those documents from the kommun
              websites to the searchable corpus the agent uses, one step at a time, with the measurements that tell
              whether each step works. Click a step to see what it does, how it is measured and the details. The
              quality of the agent&apos;s answers is measured separately, in the Benchmark view.
            </p>
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}
          {!steps && !error && <Loader2 size={18} className="mx-auto mt-10 animate-spin text-zinc-400" />}
          {steps && (
            <>
              <FlowStrip steps={steps} onSelect={select} />
              {steps.map((step) => (
                <StepCard key={step.id} step={step} open={open.has(step.id)} onToggle={() => toggle(step.id)} />
              ))}
              <section className="rounded-xl border border-zinc-200 dark:border-zinc-800">
                <button onClick={() => setGlossary((g) => !g)} className="flex w-full items-center gap-2 px-4 py-3 text-left">
                  {glossary ? <ChevronDown size={16} className="text-zinc-400" /> : <ChevronRight size={16} className="text-zinc-400" />}
                  <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Words used on this page</h2>
                </button>
                {glossary && (
                  <dl className="grid gap-x-6 gap-y-2 px-4 pb-4 text-xs sm:grid-cols-2">
                    {GLOSSARY.map(([term, meaning]) => (
                      <div key={term}>
                        <dt className="font-semibold text-zinc-800 dark:text-zinc-200">{term}</dt>
                        <dd className="text-zinc-600 dark:text-zinc-400">{meaning}</dd>
                      </div>
                    ))}
                  </dl>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
