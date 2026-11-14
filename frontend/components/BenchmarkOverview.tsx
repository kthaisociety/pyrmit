'use client';

import { Fragment, useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, Loader2, Trophy } from 'lucide-react';
import { authFetch } from '@/lib/auth';

// "Approaches tested" (issue #116): the studies the project ran, each comparing solutions on benchmark sets with the
// success rate per set, cost and time per answer, the best configuration highlighted; a configuration's full measures
// on demand. Data: GET /api/benchmark/summary (backend agentic/bench_summary.py, from the versioned result files).

export interface Cell {
  n: number;
  success: number | null;
  verdict: number | null;
  points: number | null;
  evidence: number | null;
  grounded: number | null;
  unsupported: number | null;
  tools: number | null;
  seconds: number | null;
  first: number | null;
  cost: number | null;
  files: string[];
}

export interface Config {
  key: string;
  name: string;
  settings: string;
  about: string;
  system: string;
  results: Record<string, Cell>;
  overall?: { success: number | null; points: number | null; cost: number | null };
}

export interface Study {
  key: string;
  title: string;
  about: string;
  reading: string;
  period: [string, string];
  sets: string[];
  configs: Config[];
  best_by_set: Record<string, string>;
  best: string | null;
  in_use: string | null;
}

export interface BenchmarkSummary {
  sets: { key: string; name: string; about: string; measure: 'verdict' | 'points' | 'ask' }[];
  measures: { key: string; name: string; text: string }[];
  studies: Study[];
  files?: number;
}

const MEASURE_LABEL = { verdict: 'right verdict', points: 'key points', ask: 'right move' } as const;

export function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? '–' : `${Math.round(value * 100)} %`;
}

function money(value: number | null | undefined): string {
  return value === null || value === undefined ? '–' : `$${value.toFixed(4)}`;
}

function secs(value: number | null | undefined): string {
  return value === null || value === undefined ? '–' : `${Math.round(value)} s`;
}

function period([from, to]: [string, string]): string {
  return from === to ? from : `${from} to ${to}`;
}

function Details({ config, study, setName }: { config: Config; study: Study; setName: (key: string) => string }) {
  const rows: [string, (cell: Cell) => string][] = [
    ['Answers judged', (c) => String(c.n)],
    ['Right verdict', (c) => pct(c.verdict)],
    ['Key points', (c) => pct(c.points)],
    ['Evidence seen', (c) => pct(c.evidence)],
    ['Grounding', (c) => pct(c.grounded)],
    ['Unsupported claims', (c) => (c.unsupported === null ? '–' : c.unsupported.toFixed(1))],
    ['Tool calls', (c) => (c.tools === null ? '–' : c.tools.toFixed(0))],
    ['Time (first word)', (c) => `${secs(c.seconds)}${c.first !== null ? ` (${secs(c.first)})` : ''}`],
    ['Cost per answer', (c) => money(c.cost)],
  ];
  const sets = study.sets.filter((key) => config.results[key]);
  return (
    <div className="space-y-2 bg-zinc-50 px-3 py-3 text-xs dark:bg-zinc-900/60">
      <p className="text-zinc-600 dark:text-zinc-400">{config.about}</p>
      <table className="w-full text-left">
        <thead className="text-zinc-500">
          <tr>
            <th className="py-0.5 pr-3 font-medium">Measure</th>
            {sets.map((key) => (
              <th key={key} className="py-0.5 pr-3 font-medium">{setName(key)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label} className="border-t border-zinc-200 dark:border-zinc-800">
              <td className="py-0.5 pr-3 text-zinc-500">{label}</td>
              {sets.map((key) => (
                <td key={key} className="py-0.5 pr-3">{value(config.results[key])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[11px] text-zinc-500">
        From {Array.from(new Set(sets.flatMap((key) => config.results[key].files))).join(', ')}
      </p>
    </div>
  );
}

function StudyCard({ study, summary }: { study: Study; summary: BenchmarkSummary }) {
  const [open, setOpen] = useState<string | null>(null);
  const setInfo = (key: string) => summary.sets.find((s) => s.key === key);
  const setName = (key: string) => setInfo(key)?.name ?? key;
  const best = study.configs.find((c) => c.key === study.best);

  return (
    <section aria-label={study.title} className="space-y-3 rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
      <div>
        <h2 className="text-base font-semibold">{study.title}</h2>
        <p className="text-xs text-zinc-500">{period(study.period)}</p>
        <p className="mt-1 text-sm text-zinc-700 dark:text-zinc-300">{study.about}</p>
      </div>
      {best && (
        <p className="flex items-start gap-2 rounded-lg bg-green-50 px-3 py-2 text-sm text-green-900 dark:bg-green-950/40 dark:text-green-200">
          <Trophy size={16} className="mt-0.5 shrink-0" aria-hidden />
          <span>
            Best overall: <b>{best.name}</b> ({best.settings}), {pct(best.overall?.success)} average success rate
            {best.overall?.cost !== null && best.overall?.cost !== undefined && `, ${money(best.overall.cost)} per answer`}.
          </span>
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-left text-sm">
          <thead>
            <tr className="text-xs text-zinc-500">
              <th className="py-1 pr-3 font-medium">Solution</th>
              {study.sets.map((key) => (
                <th key={key} className="py-1 pr-3 font-medium" title={setInfo(key)?.about}>
                  {setName(key)}
                  <span className="block font-normal">{MEASURE_LABEL[setInfo(key)?.measure ?? 'points']}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {study.configs.map((config) => {
              const expanded = open === config.key;
              const isBest = config.key === study.best;
              return (
                <Fragment key={config.key}>
                  <tr
                    className={`cursor-pointer border-t border-zinc-200 align-top hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-900 ${isBest ? 'bg-green-50/60 dark:bg-green-950/20' : ''}`}
                    onClick={() => setOpen(expanded ? null : config.key)}
                  >
                    <td className="py-2 pr-3">
                      <button
                        type="button"
                        className="flex items-start gap-1 text-left"
                        aria-expanded={expanded}
                        aria-label={`${config.name}, ${config.settings}: details`}
                      >
                        {expanded ? <ChevronDown size={14} className="mt-1 shrink-0" /> : <ChevronRight size={14} className="mt-1 shrink-0" />}
                        <span>
                          <span className="font-medium">{config.name}</span>
                          {isBest && (
                            <span className="ml-1.5 rounded bg-green-600 px-1.5 py-0.5 text-[10px] font-medium text-white">Best</span>
                          )}
                          {config.key === study.in_use && (
                            <span className="ml-1.5 rounded bg-blue-600 px-1.5 py-0.5 text-[10px] font-medium text-white">In use</span>
                          )}
                          <span className="block text-xs text-zinc-500">{config.settings}</span>
                        </span>
                      </button>
                    </td>
                    {study.sets.map((key) => {
                      const cell = config.results[key];
                      // Green: the best success rate on the set, every configuration that reached it (ties too)
                      const bestCell = study.configs.find((c) => c.key === study.best_by_set[key])?.results[key];
                      const top = Boolean(cell && bestCell && cell.success !== null && cell.success === bestCell.success);
                      return (
                        <td
                          key={key}
                          className={`py-2 pr-3 ${top ? 'font-semibold text-green-700 dark:text-green-400' : ''}`}
                          data-best={top || undefined}
                          title={top ? `Best on ${setName(key)}` : undefined}
                        >
                          {cell ? (
                            <>
                              <span className="text-base">{pct(cell.success)}</span>
                              <span className="block text-[11px] font-normal text-zinc-500">
                                {money(cell.cost)} · {secs(cell.seconds)}
                              </span>
                            </>
                          ) : (
                            <span className="text-zinc-400" title="Not run on this set">–</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                  {expanded && (
                    <tr>
                      <td colSpan={study.sets.length + 1}>
                        <Details config={config} study={study} setName={setName} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-sm">
        <b>What we learned.</b> {study.reading}
      </p>
    </section>
  );
}

export default function BenchmarkOverview({ onShowCases }: { onShowCases?: () => void }) {
  const [summary, setSummary] = useState<BenchmarkSummary | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    authFetch('/api/benchmark/summary')
      .then(async (res) => {
        if (!res.ok) throw new Error(`Request failed: ${res.status}`);
        const data: BenchmarkSummary = await res.json();
        if (!cancelled) setSummary(data);
      })
      .catch(() => {
        if (!cancelled) setError('Could not load the benchmark results');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <p role="alert" className="text-sm text-red-600">{error}</p>;
  if (!summary) {
    return (
      <p className="flex items-center gap-2 text-sm text-zinc-500">
        <Loader2 size={14} className="animate-spin" /> Loading the results…
      </p>
    );
  }
  if (summary.studies.length === 0) {
    return <p className="text-sm italic text-zinc-500">No benchmark results on this server.</p>;
  }

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <div className="space-y-2 text-sm text-zinc-700 dark:text-zinc-300">
        <p>
          Pyrmit answers questions on Swedish planning law. To choose how it answers, the team ran each candidate
          solution on sets of questions whose right answer is known, and had every answer scored. Each study below
          compares solutions; read the <b>success rate</b> first. The best result on each set is in green; cost and
          time are per answer. Click a solution for all its measures.
        </p>
        <details className="text-xs">
          <summary className="cursor-pointer text-zinc-600 dark:text-zinc-400">
            What each benchmark set tests ({summary.sets.length})
          </summary>
          <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {summary.sets.map((set) => (
              <div key={set.key} className="rounded-lg bg-zinc-50 px-3 py-2 dark:bg-zinc-900">
                <b>{set.name}</b> <span className="text-zinc-500">· success = {MEASURE_LABEL[set.measure]}</span>
                <p className="text-zinc-600 dark:text-zinc-400">{set.about}</p>
              </div>
            ))}
          </div>
        </details>
        <details className="text-xs">
          <summary className="cursor-pointer text-zinc-600 dark:text-zinc-400">How answers are scored</summary>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            {summary.measures.map((measure) => (
              <Fragment key={measure.key}>
                <dt className="font-medium">{measure.name}</dt>
                <dd className="text-zinc-600 dark:text-zinc-400">{measure.text}</dd>
              </Fragment>
            ))}
          </dl>
        </details>
      </div>
      {summary.studies.map((study) => (
        <StudyCard key={study.key} study={study} summary={summary} />
      ))}
      {onShowCases && (
        <p className="text-sm">
          <button type="button" onClick={onShowCases} className="text-blue-600 underline">
            See every case and how each run answered it
          </button>
        </p>
      )}
    </div>
  );
}
