'use client';

import { useState, type ReactNode } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import ChunkCard from '@/components/ChunkCard';

export interface RetrievedChunk {
  source: string;
  chunk_index: number | null;
  distance: number | null;
  content: string;
}

export interface PipelineEvent {
  stage: 'translation' | 'intent' | 'retrieval' | 'agent_output' | 'verdict' | string;
  data: Record<string, unknown>;
}

interface CallRecord {
  kind: 'llm' | 'embedding' | 'db' | string;
  name: string;
  model?: string;
  temperature?: number;
  reasoning_effort?: string | null;
  instructions?: string;
  input?: string | { role: string; content: string }[];
  output?: string;
  usage?: Record<string, number> | null;
  dimensions?: number;
  table?: string;
  k?: number;
  matches?: number;
  query?: string;
  output_chars?: number;
  duration_ms?: number;
  error?: string;
}

type StepKey = 'understand' | 'explore' | 'retrieval' | 'agents' | 'answer' | 'other';

const AGENT_LABELS: Record<string, string> = {
  law: 'Laws',
  document: 'Kommun documents',
};

const CALL_KIND_STYLES: Record<string, { label: string; className: string }> = {
  llm: { label: 'LLM', className: 'bg-violet-100 text-violet-700 dark:bg-violet-950/60 dark:text-violet-300' },
  embedding: { label: 'Embedding', className: 'bg-sky-100 text-sky-700 dark:bg-sky-950/60 dark:text-sky-300' },
  db: { label: 'Search', className: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300' },
  tool: { label: 'Tool', className: 'bg-orange-100 text-orange-700 dark:bg-orange-950/60 dark:text-orange-300' },
};

/** Which pipeline step an API call belongs to, from its kind and name. */
function stepOf(call: CallRecord): StepKey {
  const name = call.name.toLowerCase();
  if (call.kind === 'tool' || (call.kind === 'llm' && name.startsWith('agent turn'))) return 'explore';
  if (call.kind === 'llm' && /rewrite|translation/.test(name)) return 'understand';
  if (call.kind === 'embedding' || call.kind === 'db') return 'retrieval';
  if (call.kind === 'llm' && /analysis|agent/.test(name)) return 'agents';
  if (call.kind === 'llm' && /answer/.test(name)) return 'answer';
  return 'other';
}

const costOf = (calls: CallRecord[]) => calls.reduce((sum, call) => sum + (call.usage?.cost ?? 0), 0);
const msOf = (calls: CallRecord[]) => calls.reduce((sum, call) => sum + (call.duration_ms ?? 0), 0);
const tokensOf = (calls: CallRecord[]) => calls.reduce((sum, call) => sum + (call.usage?.total_tokens ?? 0), 0);

function formatCost(cost: number): string {
  if (cost <= 0) return '';
  return `$${cost < 0.01 ? cost.toFixed(4) : cost.toFixed(3)}`;
}

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[100px_1fr] gap-2 text-xs">
      <div className="font-medium text-zinc-500 dark:text-zinc-400">{label}</div>
      <div className="min-w-0 break-words text-zinc-800 dark:text-zinc-100">{children}</div>
    </div>
  );
}

function Missing() {
  return <span className="italic text-red-500">not found</span>;
}

function TextBlock({ label, text }: { label: string; text: string }) {
  return (
    <div className="space-y-1">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">{label}</div>
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-zinc-950 px-3 py-2 text-[11px] leading-relaxed text-zinc-100">
        {text}
      </pre>
    </div>
  );
}

function JsonToggle({ label, value }: { label: string; value: unknown }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-zinc-200 dark:border-zinc-700">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs font-medium text-zinc-700 dark:text-zinc-200"
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        {label}
      </button>
      {open && (
        <pre className="max-h-80 overflow-auto border-t border-zinc-200 bg-zinc-950 px-3 py-2 text-[11px] leading-relaxed text-zinc-100 dark:border-zinc-700">
          <code>{JSON.stringify(value, null, 2)}</code>
        </pre>
      )}
    </div>
  );
}

/** One API call, collapsed to a single line: kind, name, model, tokens, cost, duration. */
function CallLine({ call }: { call: CallRecord }) {
  const [open, setOpen] = useState(false);
  const kind = CALL_KIND_STYLES[call.kind] ?? { label: call.kind, className: 'bg-zinc-100 text-zinc-600' };
  const inputMessages = Array.isArray(call.input) ? call.input : null;
  const reasoning = call.usage?.reasoning_tokens;

  return (
    <div className="rounded-lg border border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-950/70">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left">
        <span className="text-zinc-400">{open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</span>
        <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${kind.className}`}>{kind.label}</span>
        <span className="min-w-0 flex-1 truncate text-xs text-zinc-700 dark:text-zinc-200">
          {call.name}
          {call.model && <span className="ml-1.5 font-mono text-[10px] text-zinc-400">{call.model}</span>}
          {call.reasoning_effort && <span className="ml-1 text-[10px] text-zinc-400">· {call.reasoning_effort}</span>}
        </span>
        {call.error && <span className="text-[10px] font-medium text-red-500">failed</span>}
        {call.usage?.total_tokens !== undefined && (
          <span className="text-[10px] text-zinc-500">
            {call.usage.total_tokens} tok{reasoning ? ` (${reasoning} reasoning)` : ''}
          </span>
        )}
        {call.usage?.cost !== undefined && (
          <span className="text-[10px] font-medium text-amber-600 dark:text-amber-400">{formatCost(call.usage.cost)}</span>
        )}
        {call.duration_ms !== undefined && (
          <span className="font-mono text-[10px] text-zinc-500">{formatMs(call.duration_ms)}</span>
        )}
      </button>
      {open && (
        <div className="space-y-2 border-t border-zinc-200 px-3 py-2 dark:border-zinc-700">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-500">
            {call.dimensions !== undefined && <span>dimensions: {call.dimensions}</span>}
            {call.table && <span>source: <span className="font-mono">{call.table}</span></span>}
            {call.k !== undefined && <span>k: {call.k}</span>}
            {call.matches !== undefined && <span>results: {call.matches}</span>}
            {call.usage && Object.entries(call.usage)
              .filter(([key]) => key !== 'cost')
              .map(([key, value]) => <span key={key}>{key}: {value}</span>)}
          </div>
          {call.error && <TextBlock label="Error" text={call.error} />}
          {call.query && <TextBlock label="Query" text={call.query} />}
          {call.instructions && <TextBlock label="System prompt" text={call.instructions} />}
          {typeof call.input === 'string' && (
            <TextBlock label={call.kind === 'embedding' ? 'Embedded text' : 'Prompt'} text={call.input} />
          )}
          {inputMessages?.map((message, i) => (
            <TextBlock key={i} label={`Message ${i + 1} · ${message.role}`} text={message.content} />
          ))}
          {call.output && <TextBlock label="Output" text={call.output} />}
        </div>
      )}
    </div>
  );
}

/** A pipeline step: one summary line (always visible), details and its API calls when expanded. */
function Step({
  index,
  title,
  summary,
  calls,
  children,
}: {
  index: number;
  title: string;
  summary: ReactNode;
  calls: CallRecord[];
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const cost = costOf(calls);
  const ms = msOf(calls);
  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-700">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 px-3 py-2 text-left">
        <span className="text-zinc-400">{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</span>
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-[10px] font-semibold text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
          {index}
        </span>
        <span className="shrink-0 text-xs font-semibold text-zinc-800 dark:text-zinc-100">{title}</span>
        <span className="min-w-0 flex-1 truncate text-xs text-zinc-500">{summary}</span>
        {cost > 0 && <span className="text-[10px] font-medium text-amber-600 dark:text-amber-400">{formatCost(cost)}</span>}
        {ms > 0 && <span className="font-mono text-[10px] text-zinc-500">{formatMs(ms)}</span>}
      </button>
      {open && (
        <div className="space-y-2.5 border-t border-zinc-200 px-3 py-2.5 dark:border-zinc-700">
          {children}
          {calls.length > 0 && (
            <div className="space-y-1">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
                API calls ({calls.length})
              </div>
              {calls.map((call, i) => (
                <CallLine key={`${call.name}-${i}`} call={call} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ChunkList({ matches }: { matches: RetrievedChunk[] }) {
  if (matches.length === 0) return <div className="text-xs italic text-zinc-500">No chunks retrieved.</div>;
  return (
    <div className="space-y-1">
      {matches.map((chunk, j) => (
        <ChunkCard
          key={`${chunk.source}-${chunk.chunk_index}-${j}`}
          rank={j + 1}
          source={chunk.source}
          chunkIndex={chunk.chunk_index}
          distance={chunk.distance}
          content={chunk.content}
        />
      ))}
    </div>
  );
}

export default function PipelineTrace({ events }: { events: PipelineEvent[] }) {
  const calls = events.filter((e) => e.stage === 'call').map((e) => e.data as unknown as CallRecord);
  const callsBy = (step: StepKey) => calls.filter((call) => stepOf(call) === step);
  const translation = events.find((e) => e.stage === 'translation')?.data;
  const intent = events.find((e) => e.stage === 'intent')?.data;
  const localQuery = events.find((e) => e.stage === 'local_query')?.data;
  const retrievals = events.filter((e) => e.stage === 'retrieval').map((e) => e.data);
  const agentOutputs = events.filter((e) => e.stage === 'agent_output').map((e) => e.data);
  const verdict = events.find((e) => e.stage === 'verdict')?.data;

  const feasibility = intent?.route === 'feasibility';
  const agentRoute = intent?.route === 'agent';
  const exploreCalls = callsBy('explore');
  const kommuner = Array.isArray(localQuery?.kommuner) ? (localQuery.kommuner as string[]) : [];
  const totalCost = costOf(calls);
  const retrievalSummary = retrievals
    .map((r) => `${((r.matches as unknown[]) ?? []).length} ${(AGENT_LABELS[String(r.agent)] ?? String(r.agent)).toLowerCase()}`)
    .join(' + ');

  let index = 0;
  return (
    <div className="space-y-2 pt-1">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-zinc-500">
        <span
          className={`rounded-full px-2 py-0.5 font-medium ${
            feasibility
              ? 'bg-blue-100 text-blue-700 dark:bg-blue-950/60 dark:text-blue-300'
              : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300'
          }`}
        >
          {agentRoute ? 'Agent' : feasibility ? 'Feasibility analysis' : 'General RAG'}
        </span>
        <span>{calls.length} API calls</span>
        <span>{formatMs(msOf(calls))}</span>
        <span>{tokensOf(calls)} tokens</span>
        {totalCost > 0 && <span className="font-medium text-amber-600 dark:text-amber-400">{formatCost(totalCost)}</span>}
      </div>

      {(translation || (intent && !agentRoute)) && (
        <Step
          index={++index}
          title="Understand"
          summary={String(translation?.translated ?? '')}
          calls={callsBy('understand')}
        >
          {translation && (
            <>
              <Row label="Original">{String(translation.original ?? '')}</Row>
              <Row label="English">{String(translation.translated ?? '')}</Row>
              {localQuery && <Row label="Swedish">{localQuery.query_sv ? String(localQuery.query_sv) : <Missing />}</Row>}
              {Boolean(translation.used_history) && <Row label="History">used to resolve the question</Row>}
            </>
          )}
          {intent && (
            <Row label="Route">
              {feasibility
                ? `feasibility (location: ${String(intent.location)}, units: ${String(intent.units)})`
                : 'general RAG (no location + number of units in the question)'}
            </Row>
          )}
        </Step>
      )}

      {exploreCalls.length > 0 && (
        <Step
          index={++index}
          title="Explore (agent)"
          summary={`${exploreCalls.filter((c) => c.kind === 'tool').length} tool calls · ${
            exploreCalls.filter((c) => c.kind === 'llm').length} model turns`}
          calls={exploreCalls}
        />
      )}

      {(retrievals.length > 0 || callsBy('retrieval').length > 0) && (
        <Step
          index={++index}
          title={agentRoute ? 'Sources' : 'Retrieve'}
          summary={[
            retrievalSummary,
            localQuery ? (kommuner.length ? `kommun ${kommuner.join(', ')}` : 'all kommuner') : '',
          ].filter(Boolean).join(' · ')}
          calls={callsBy('retrieval')}
        >
          {localQuery && (
            <Row label="Kommun filter">{kommuner.length ? kommuner.join(', ') : 'none detected (all kommuner)'}</Row>
          )}
          {retrievals.map((retrieval, i) => (
            <div key={`${String(retrieval.agent)}-${i}`} className="space-y-1">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
                {AGENT_LABELS[String(retrieval.agent)] ?? String(retrieval.agent)}
              </div>
              {retrieval.embedding_ok === false && (
                <div className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-950/50 dark:text-red-300">
                  Embedding failed: no retrieval was possible (check the embedding provider key).
                </div>
              )}
              <ChunkList matches={(retrieval.matches as RetrievedChunk[] | undefined) ?? []} />
            </div>
          ))}
        </Step>
      )}

      {(agentOutputs.length > 0 || callsBy('agents').length > 0) && (
        <Step
          index={++index}
          title="Agents"
          summary={`${agentOutputs.length} agent outputs`}
          calls={callsBy('agents')}
        >
          {agentOutputs.map((output, i) => (
            <JsonToggle
              key={`${String(output.agent)}-${i}`}
              label={`${AGENT_LABELS[String(output.agent)] ?? String(output.agent)} agent (JSON)`}
              value={output.output}
            />
          ))}
        </Step>
      )}

      {verdict && (
        <Step
          index={++index}
          title="Verdict"
          summary={`${String(verdict.feasibility ?? '')} · ${String(verdict.confidence ?? '')}%`}
          calls={[]}
        >
          <Row label="Feasibility">{String(verdict.feasibility ?? '')}</Row>
          <Row label="Confidence">{String(verdict.confidence ?? '')}%</Row>
          <Row label="Summary">{String(verdict.summary ?? '')}</Row>
        </Step>
      )}

      {callsBy('answer').length > 0 && (
        <Step
          index={++index}
          title="Answer"
          summary={callsBy('answer')
            .map((call) => [call.model, call.reasoning_effort].filter(Boolean).join(' · '))
            .join(', ')}
          calls={callsBy('answer')}
        />
      )}

      {callsBy('other').length > 0 && (
        <Step index={++index} title="Other calls" summary="" calls={callsBy('other')} />
      )}
    </div>
  );
}
