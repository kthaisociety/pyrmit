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

const AGENT_LABELS: Record<string, string> = {
  law: 'Law chunks',
  document: 'Document chunks',
};

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[110px_1fr] gap-2 text-xs">
      <div className="font-medium text-zinc-500 dark:text-zinc-400">{label}</div>
      <div className="min-w-0 break-words text-zinc-800 dark:text-zinc-100">{children}</div>
    </div>
  );
}

function Missing() {
  return <span className="italic text-red-500">not found</span>;
}

function StageBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-zinc-400">{title}</div>
      {children}
    </div>
  );
}

function JsonToggle({ label, value }: { label: string; value: unknown }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-700">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-zinc-700 dark:text-zinc-200"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {label}
      </button>
      {open && (
        <pre className="max-h-96 overflow-auto border-t border-zinc-200 bg-zinc-950 px-3 py-2 text-[11px] leading-relaxed text-zinc-100 dark:border-zinc-700">
          <code>{JSON.stringify(value, null, 2)}</code>
        </pre>
      )}
    </div>
  );
}

interface CallRecord {
  kind: 'llm' | 'embedding' | 'db' | string;
  name: string;
  model?: string;
  temperature?: number;
  instructions?: string;
  input?: string | { role: string; content: string }[];
  output?: string;
  usage?: Record<string, number> | null;
  dimensions?: number;
  table?: string;
  k?: number;
  matches?: number;
  query?: string;
  duration_ms?: number;
  error?: string;
}

const CALL_KIND_STYLES: Record<string, { label: string; className: string }> = {
  llm: { label: 'LLM', className: 'bg-violet-100 text-violet-700 dark:bg-violet-950/60 dark:text-violet-300' },
  embedding: { label: 'Embedding', className: 'bg-sky-100 text-sky-700 dark:bg-sky-950/60 dark:text-sky-300' },
  db: { label: 'pgvector', className: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300' },
};

function TextBlock({ label, text }: { label: string; text: string }) {
  return (
    <div className="space-y-1">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">{label}</div>
      <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-zinc-950 px-3 py-2 text-[11px] leading-relaxed text-zinc-100">
        {text}
      </pre>
    </div>
  );
}

function CallCard({ call, index }: { call: CallRecord; index: number }) {
  const [open, setOpen] = useState(false);
  const kind = CALL_KIND_STYLES[call.kind] ?? { label: call.kind, className: 'bg-zinc-100 text-zinc-600' };
  const tokens = call.usage?.total_tokens;
  const inputMessages = Array.isArray(call.input) ? call.input : null;

  return (
    <div className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-950/70">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 px-3 py-2 text-left">
        <span className="text-zinc-400">{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</span>
        <span className="text-[11px] font-semibold text-zinc-400">#{index + 1}</span>
        <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${kind.className}`}>{kind.label}</span>
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-zinc-800 dark:text-zinc-100">{call.name}</span>
        {call.error && <span className="text-[10px] font-medium text-red-500">failed</span>}
        {tokens !== undefined && <span className="text-[10px] text-zinc-500">{tokens} tok</span>}
        {call.duration_ms !== undefined && (
          <span className="font-mono text-[10px] text-zinc-500">{call.duration_ms} ms</span>
        )}
      </button>
      {open && (
        <div className="space-y-2 border-t border-zinc-200 px-3 py-2 dark:border-zinc-700">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-500">
            {call.model && <span>model: <span className="font-mono">{call.model}</span></span>}
            {call.temperature !== undefined && call.temperature !== null && <span>temperature: {call.temperature}</span>}
            {call.dimensions !== undefined && <span>dimensions: {call.dimensions}</span>}
            {call.table && <span>table: <span className="font-mono">{call.table}</span></span>}
            {call.k !== undefined && <span>k: {call.k}</span>}
            {call.matches !== undefined && <span>rows: {call.matches}</span>}
            {call.usage && Object.entries(call.usage).map(([key, value]) => (
              <span key={key}>{key}: {value}</span>
            ))}
          </div>
          {call.error && <TextBlock label="Error" text={call.error} />}
          {call.query && <TextBlock label="SQL" text={call.query} />}
          {call.instructions && <TextBlock label="System prompt (instructions)" text={call.instructions} />}
          {typeof call.input === 'string' && (
            <TextBlock label={call.kind === 'embedding' ? 'Embedded text' : 'Prompt (input)'} text={call.input} />
          )}
          {inputMessages?.map((message, i) => (
            <TextBlock key={i} label={`Input message ${i + 1} · ${message.role}`} text={message.content} />
          ))}
          {call.output && <TextBlock label="Output" text={call.output} />}
        </div>
      )}
    </div>
  );
}

export default function PipelineTrace({ events }: { events: PipelineEvent[] }) {
  const calls = events.filter((e) => e.stage === 'call').map((e) => e.data as unknown as CallRecord);
  const totalMs = calls.reduce((total, call) => total + (call.duration_ms ?? 0), 0);
  const totalTokens = calls.reduce((total, call) => total + (call.usage?.total_tokens ?? 0), 0);
  const translation = events.find((e) => e.stage === 'translation')?.data;
  const intent = events.find((e) => e.stage === 'intent')?.data;
  const retrievals = events.filter((e) => e.stage === 'retrieval').map((e) => e.data);
  const agentOutputs = events.filter((e) => e.stage === 'agent_output').map((e) => e.data);
  const verdict = events.find((e) => e.stage === 'verdict')?.data;

  return (
    <div className="space-y-4 pt-1">
      {calls.length > 0 && (
        <StageBlock title={`API calls · ${calls.length} calls · Σ ${(totalMs / 1000).toFixed(1)} s · ${totalTokens} tokens`}>
          <div className="space-y-1.5">
            {calls.map((call, i) => (
              <CallCard key={`${call.name}-${i}`} call={call} index={i} />
            ))}
          </div>
        </StageBlock>
      )}

      {translation && (
        <StageBlock title="1 · Query rewrite">
          <Row label="Original">{String(translation.original ?? '')}</Row>
          <Row label="Rewritten (EN)">{String(translation.translated ?? '')}</Row>
          <Row label="Used history">{translation.used_history ? 'yes' : 'no'}</Row>
        </StageBlock>
      )}

      {intent && (
        <StageBlock title="2 · Intent parsing (regex)">
          <Row label="Location">{intent.location ? String(intent.location) : <Missing />}</Row>
          <Row label="Units">{intent.units !== null && intent.units !== undefined ? String(intent.units) : <Missing />}</Row>
          <Row label="Project type">{String(intent.project_type ?? '')}</Row>
          <Row label="Route">
            <span
              className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                intent.route === 'feasibility'
                  ? 'bg-blue-100 text-blue-700 dark:bg-blue-950/60 dark:text-blue-300'
                  : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300'
              }`}
            >
              {intent.route === 'feasibility' ? 'Multi-agent feasibility' : 'General RAG'}
            </span>
            {intent.route !== 'feasibility' && (
              <span className="ml-2 text-zinc-500">(location or units missing)</span>
            )}
          </Row>
        </StageBlock>
      )}

      {retrievals.map((retrieval, i) => {
        const matches = (retrieval.matches as RetrievedChunk[] | undefined) ?? [];
        const agent = String(retrieval.agent ?? '');
        return (
          <StageBlock key={`${agent}-${i}`} title={`3 · Retrieval — ${AGENT_LABELS[agent] ?? agent}`}>
            <Row label="Search query">{String(retrieval.query ?? '')}</Row>
            {retrieval.embedding_ok === false && (
              <div className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700 dark:bg-red-950/50 dark:text-red-300">
                Embedding failed — no retrieval was possible (check OPENAI_API_KEY).
              </div>
            )}
            {matches.length === 0 ? (
              <div className="text-xs italic text-zinc-500">No chunks retrieved.</div>
            ) : (
              <div className="space-y-1.5">
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
            )}
          </StageBlock>
        );
      })}

      {agentOutputs.length > 0 && (
        <StageBlock title="4 · Agent outputs (LLM JSON)">
          <div className="space-y-1.5">
            {agentOutputs.map((output, i) => (
              <JsonToggle
                key={`${String(output.agent)}-${i}`}
                label={`${AGENT_LABELS[String(output.agent)] ?? String(output.agent)} agent`}
                value={output.output}
              />
            ))}
          </div>
        </StageBlock>
      )}

      {verdict && (
        <StageBlock title="5 · Verdict (rule-based)">
          <Row label="Feasibility">{String(verdict.feasibility ?? '')}</Row>
          <Row label="Confidence">{String(verdict.confidence ?? '')}%</Row>
          <Row label="Summary">{String(verdict.summary ?? '')}</Row>
        </StageBlock>
      )}
    </div>
  );
}
