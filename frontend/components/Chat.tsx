'use client';

import { useState, useEffect, FormEvent, ReactNode, useRef } from 'react';
import Image from 'next/image';
import {
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  FileSearch,
  FileText,
  Image as ImageIcon,
  Layers,
  List,
  Loader2,
  Map as MapIcon,
  MapPin,
  Microscope,
  Regex,
  Scale,
  Search,
  Sparkles,
  Wrench,
} from 'lucide-react';
import { authFetch } from '@/lib/auth';
import ChunkCard from '@/components/ChunkCard';
import PipelineTrace, { type PipelineEvent, type RetrievedChunk } from '@/components/PipelineTrace';
import SourceViewer, { type Citation } from '@/components/SourceViewer';
import CitedMarkdown from '@/components/CitedMarkdown';
import PlaceChip from '@/components/place/PlaceChip';
import PlacePanel from '@/components/place/PlacePanel';
import { placeFromHistory, placeLabel, type Pin } from '@/lib/place';

interface Message {
  id?: number;
  role: string;
  content: string;
  session_id?: string;
  created_at?: string;
  steps?: Step[];
  pipeline?: PipelineEvent[];
  trace?: PipelineEvent[] | null; // saved pipeline events, from the history endpoint
  status?: string | null; // assistant messages from the history: "streaming" | "done" | "error"
}

interface Step {
  type: 'thinking' | 'tool_call' | 'tool_result';
  label?: string;   // thinking
  name?: string;    // tool_call / tool_result
  input?: string;   // tool_call
  result?: string;  // tool_result
  chunks?: number;  // tool_result (agent): passages returned
  ms?: number;      // tool_result (agent): duration
  done: boolean;
}

interface StreamEvent {
  type: string;
  delta?: string;
  token?: string;
  session_id?: string;
  label?: string;
  name?: string;
  input?: string;
  result?: string;
  chunks?: number;
  ms?: number;
  message?: string;
  stage?: string;
  data?: Record<string, unknown>;
}

const STREAM_STALL_MS = 45_000; // no bytes for this long (keep-alives every 10 s) = dead connection

interface ChatProps {
  sessionId: string | null;
  onSessionCreated: (newSessionId: string) => void;
  user: { name: string } | null;
}

const EXAMPLE_PROMPTS = [
  "Can I build 20 apartments in Södermalm?",
  "What does PBL say about building height restrictions?",
  "Explain detaljplan requirements for commercial buildings",
  "What are the setback rules for residential construction?",
];

function extractSseEvents(rawBuffer: string): { events: StreamEvent[]; remainder: string } {
  const normalized = rawBuffer.replace(/\r\n/g, '\n');
  const frames = normalized.split('\n\n');
  const remainder = frames.pop() ?? '';
  const events: StreamEvent[] = [];

  for (const frame of frames) {
    const dataLines = frame
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart());

    if (dataLines.length === 0) {
      continue;
    }

    try {
      events.push(JSON.parse(dataLines.join('\n')) as StreamEvent);
    } catch {
      continue;
    }
  }

  return { events, remainder };
}

function parseAssistantContent(content: string): { body: string; sources: string[] } {
  const marker = '\n\n---\n**Sources**\n';
  const markerIndex = content.lastIndexOf(marker);

  if (markerIndex === -1) {
    return { body: content, sources: [] };
  }

  const body = content.slice(0, markerIndex).trimEnd();
  const sources = content
    .slice(markerIndex + marker.length)
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.startsWith('- '))
    .map((line) => line.slice(2).trim().replace(/^\[\d+\]\s*/, '')) // agent answers: "- [n] label"
    .filter(Boolean);

  return { body, sources };
}

function getCitations(pipeline: PipelineEvent[]): Citation[] {
  const event = pipeline.find((item) => item.stage === 'citations');
  return ((event?.data.items as Citation[] | undefined) ?? []);
}

// One row of the live process timeline: a status step ("Understanding your question") or a tool call
interface ProcessItem {
  kind: 'thinking' | 'tool';
  name: string; // tool name, or the status label
  input?: string;
  result?: string;
  chunks?: number;
  ms?: number;
  done: boolean;
}

// Steps of an answer still generating in the background (the chat was reopened mid-run): the saved trace
// holds the tool calls made so far
function stepsFromTrace(pipeline: PipelineEvent[]): Step[] {
  return pipeline
    .filter((event) => event.stage === 'call' && event.data.kind === 'tool')
    .flatMap((event) => {
      const call = event.data as { name?: string; tool?: string; input?: string; output?: string; matches?: number; duration_ms?: number };
      const name = call.tool ?? call.name?.split('(')[0] ?? 'tool';
      return [
        { type: 'tool_call', name, input: call.input, done: true },
        { type: 'tool_result', name, result: call.output ?? '', chunks: call.matches, ms: call.duration_ms, done: true },
      ] satisfies Step[];
    });
}

function getProcessItems(steps: Step[]): ProcessItem[] {
  const items: ProcessItem[] = [];

  for (const step of steps) {
    if (step.type === 'thinking') {
      const label = step.label?.trim();
      if (label) items.push({ kind: 'thinking', name: label, done: step.done });
      continue;
    }

    if (step.type === 'tool_call') {
      items.push({ kind: 'tool', name: step.name || 'tool', input: step.input, done: step.done });
      continue;
    }

    // Results of parallel calls arrive in call order: the oldest call of that tool without a result
    const result = { result: step.result ?? '', chunks: step.chunks, ms: step.ms, done: true };
    const call = items.find((item) => item.kind === 'tool' && item.name === step.name && item.result === undefined);
    if (call) {
      Object.assign(call, result);
    } else {
      items.push({ kind: 'tool', name: step.name || 'tool', ...result });
    }
  }

  return items;
}

const TOOL_INFO: Record<string, { label: string; icon: typeof Search }> = {
  find_kommun: { label: 'Kommun', icon: MapPin },
  search: { label: 'Search', icon: Search },
  grep: { label: 'Grep', icon: Regex },
  list_documents: { label: 'Documents', icon: List },
  read: { label: 'Read', icon: BookOpen },
  law_section: { label: 'Law', icon: Scale },
  plans: { label: 'Plans', icon: Layers },
  plan_rules: { label: 'Plan rules', icon: FileText },
  view_map_area: { label: 'Map', icon: MapIcon },
  view_pdf_page: { label: 'PDF page', icon: ImageIcon },
  embed_query: { label: 'Embed', icon: Sparkles },
  retrieve_local_corpus: { label: 'Retrieve', icon: Search },
  retrieve_law_chunks: { label: 'Laws', icon: Scale },
  retrieve_document_chunks: { label: 'Documents', icon: FileText },
  law_agent: { label: 'Law agent', icon: Scale },
  document_agent: { label: 'Document agent', icon: FileText },
};

function toolInfo(name: string) {
  return TOOL_INFO[name] ?? {
    label: name.replace(/_/g, ' ').replace(/^\w/, (char) => char.toUpperCase()),
    icon: Wrench,
  };
}

// What the call asked for, in one line: the agent sends its arguments as JSON, the RAG pipeline as plain text
function describeToolCall(name: string, input?: string): { text: string; tags: string[] } {
  let args: Record<string, unknown> | null = null;
  try {
    const parsed = JSON.parse(input ?? '');
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) args = parsed;
  } catch {
    // plain text input
  }
  if (!args) {
    return { text: input ?? '', tags: [] };
  }

  const values = args;
  const arg = (key: string) => (values[key] === undefined || values[key] === null ? '' : String(values[key]).trim());
  const quoted = (key: string) => (arg(key) ? `“${arg(key)}”` : '');
  const tags = (...items: string[]) => items.filter(Boolean);
  const scope = arg('scope') && arg('scope') !== 'all' ? arg('scope') : '';

  switch (name) {
    case 'find_kommun':
      return { text: arg('place'), tags: [] };
    case 'search':
      return { text: quoted('query'), tags: tags(arg('kommun'), scope) };
    case 'grep':
      return { text: `/${arg('pattern')}/`, tags: tags(arg('kommun'), scope) };
    case 'list_documents':
      return { text: arg('kommun'), tags: tags(arg('doc_type'), quoted('title_contains')) };
    case 'read':
      return {
        text: arg('chunk_id') || arg('doc_id'),
        tags: tags(!arg('chunk_id') && Number(arg('start')) > 0 ? `from #${arg('start')}` : ''),
      };
    case 'law_section':
      return { text: `${arg('law')} ${arg('section')}`, tags: [] };
    case 'plans':
      return { text: arg('kommun'), tags: tags(quoted('query'), arg('status')) };
    case 'plan_rules':
      return { text: arg('plan_id'), tags: tags(arg('topic')) };
    case 'view_map_area':
      return { text: `around ${quoted('around')}`, tags: tags(arg('doc_id'), arg('page') && `p. ${arg('page')}`) };
    case 'view_pdf_page':
      return { text: arg('doc_id'), tags: tags(`p. ${arg('page') || '1'}`) };
    default:
      return { text: Object.values(values).map(String).join(' · '), tags: [] };
  }
}

// The document a read / plan_rules call opened, from the first line of its result ("<title> (<kommun>, ...")
function resultTitle(item: ProcessItem): string | null {
  const first = (item.result ?? '').split('\n')[0];
  const pattern = item.name === 'read' ? / \([^()]*\d+ chunks.*$/ : item.name === 'plan_rules' ? / \([^()]*\), status .*$/ : null;
  return pattern && pattern.test(first) ? first.replace(pattern, '') : null;
}

function formatDuration(ms: number): string {
  return ms < 100 ? '<0.1 s' : `${(ms / 1000).toFixed(1)} s`;
}

const TOOL_ERROR =/^(Unknown|No kommun|No section|No plan registry|Invalid regex|Bad arguments|Only crawled|PDF file missing)|is not printed as text/;

function plural(count: number, word: string, many = `${word}s`): string {
  return `${count} ${count === 1 ? word : many}`;
}

// What the call returned, in a few words (the agent's result text is cut at 300 characters)
function summarizeToolCall(item: ProcessItem): { text: string; error: boolean } {
  const result = item.result ?? '';
  const first = result.split('\n')[0].trim();
  if (TOOL_ERROR.test(first)) {
    return { text: first.length > 60 ? `${first.slice(0, 60)}…` : first, error: true };
  }

  const count = (pattern: RegExp) => {
    const match = result.match(pattern);
    return match ? Number(match[1]) : null;
  };
  let n: number | null = null;
  switch (item.name) {
    case 'find_kommun': {
      // One line per matching kommun ("Vallentuna (0115) – Stockholms län, ..."): the others are ambiguities
      const others = result.split('\n').filter((line) => / \(\d{4}\) – /.test(line)).length - 1;
      return { text: first.split(' – ')[0] + (others > 0 ? ` +${others}` : ''), error: false };
    }
    case 'grep':
      n = count(/^(\d+) matching chunks/);
      if (n !== null) return { text: plural(n, 'match', 'matches'), error: n === 0 };
      break;
    case 'list_documents':
      n = count(/^(\d+) documents/);
      if (n !== null) return { text: plural(n, 'document'), error: n === 0 };
      break;
    case 'plans':
      n = count(/^(\d+) of \d+ plans/);
      if (n !== null) return { text: plural(n, 'plan'), error: n === 0 };
      break;
    case 'plan_rules':
      n = count(/(\d+) provisions:/);
      if (n !== null) return { text: plural(n, 'rule'), error: false };
      if (result.includes('No provisions extracted')) return { text: 'no rules extracted', error: true };
      break;
    case 'view_map_area':
    case 'view_pdf_page':
      return { text: 'image', error: false };
  }

  if (item.chunks !== undefined) {
    return item.chunks === 0
      ? { text: 'no results', error: true }
      : { text: plural(item.chunks, 'passage'), error: false };
  }
  return { text: first.length > 40 ? `${first.slice(0, 40)}…` : first, error: false };
}

function CollapsibleMetaSection({
  title,
  icon,
  badge,
  children,
  defaultOpen = false,
  forceOpen = false,
}: {
  title: string;
  icon: ReactNode;
  badge?: string;
  children: ReactNode;
  defaultOpen?: boolean;
  forceOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen || forceOpen);
  const visibleOpen = forceOpen || open;

  return (
    <section className="overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50/70 dark:bg-zinc-900/40">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-3 py-2 text-left transition-colors hover:bg-zinc-100 dark:hover:bg-zinc-800/60"
      >
        <div className="flex size-7 items-center justify-center rounded-lg border border-zinc-200 bg-white text-zinc-600 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-300">
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-zinc-500 dark:text-zinc-400">
            {title}
          </div>
        </div>
        {badge && (
          <span className="rounded-full border border-zinc-200 bg-white px-2 py-0.5 text-[10px] font-medium text-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-300">
            {badge}
          </span>
        )}
        {visibleOpen ? <ChevronDown size={14} className="text-zinc-400" /> : <ChevronRight size={14} className="text-zinc-400" />}
      </button>
      {visibleOpen && (
        <div className="border-t border-zinc-200 px-3 pb-3 pt-2 dark:border-zinc-700">
          {children}
        </div>
      )}
    </section>
  );
}

const TABLE_LABELS: Record<string, string> = {
  law: 'Law',
  document: 'Planning document',
};

interface SourceChunk extends RetrievedChunk {
  agent: string;
}

function getRetrievedChunksBySource(pipeline: PipelineEvent[]): Map<string, SourceChunk[]> {
  const bySource = new Map<string, SourceChunk[]>();
  const seen = new Set<string>();

  for (const event of pipeline) {
    if (event.stage !== 'retrieval') continue;
    const agent = String(event.data.agent ?? '');
    for (const match of (event.data.matches as RetrievedChunk[] | undefined) ?? []) {
      const key = `${agent}:${match.source}:${match.chunk_index}`;
      if (seen.has(key)) continue;
      seen.add(key);
      bySource.set(match.source, [...(bySource.get(match.source) ?? []), { ...match, agent }]);
    }
  }

  for (const chunks of bySource.values()) {
    chunks.sort((a, b) => (a.distance ?? 1) - (b.distance ?? 1));
  }
  return bySource;
}

function SourceList({ sources, pipeline }: { sources: string[]; pipeline: PipelineEvent[] }) {
  const [selected, setSelected] = useState<string | null>(null);
  const chunksBySource = getRetrievedChunksBySource(pipeline);
  const selectedChunks = selected ? chunksBySource.get(selected) ?? [] : [];

  return (
    <div className="space-y-3 pt-1">
      <div className="flex flex-wrap gap-2">
        {sources.map((source, index) => {
          const count = chunksBySource.get(source)?.length ?? 0;
          const active = selected === source;
          return (
            <button
              key={`${source}-${index}`}
              onClick={() => setSelected(active ? null : source)}
              className={`rounded-full border px-2.5 py-1 text-[11px] transition-colors ${
                active
                  ? 'border-blue-500 bg-blue-50 text-blue-700 dark:border-blue-500 dark:bg-blue-950/60 dark:text-blue-300'
                  : 'border-zinc-200 bg-white text-zinc-600 hover:border-zinc-400 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-300 dark:hover:border-zinc-500'
              }`}
            >
              {source}
              {count > 0 && <span className="ml-1 opacity-60">· {count}</span>}
            </button>
          );
        })}
      </div>

      {selected && (
        selectedChunks.length > 0 ? (
          <div className="space-y-1.5">
            {selectedChunks.map((chunk, i) => (
              <ChunkCard
                key={`${chunk.agent}-${chunk.chunk_index}-${i}`}
                source={chunk.source}
                chunkIndex={chunk.chunk_index}
                distance={chunk.distance}
                content={chunk.content}
                meta={[TABLE_LABELS[chunk.agent] ?? chunk.agent]}
                defaultOpen={selectedChunks.length === 1}
              />
            ))}
          </div>
        ) : (
          <p className="text-xs italic text-zinc-500">
            No chunk details were recorded for this answer (it was generated before pipeline tracing was added).
          </p>
        )
      )}
    </div>
  );
}

// Numbered sources of an agent answer: the same numbers as the [n] in the text, each opens the source panel
function CitationList({ citations, onOpen }: { citations: Citation[]; onOpen: (citation: Citation) => void }) {
  return (
    <div className="space-y-1.5 pt-1">
      {citations.map((citation) => (
        <button
          key={citation.n}
          onClick={() => onOpen(citation)}
          className="flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-zinc-700 hover:bg-zinc-100 dark:text-zinc-200 dark:hover:bg-zinc-800"
        >
          <span className="mt-px rounded bg-blue-100 px-1.5 font-semibold text-blue-700 dark:bg-blue-950 dark:text-blue-300">
            {citation.n}
          </span>
          <span className="min-w-0 flex-1">{citation.label}</span>
          <span className="text-zinc-400">{citation.chunks.length} passage{citation.chunks.length > 1 ? 's' : ''}</span>
        </button>
      ))}
    </div>
  );
}

// Inspection panels shown under a finished answer
function AnswerDetails({ sources, pipeline, citations, onOpenCitation }: {
  sources: string[];
  pipeline: PipelineEvent[];
  citations: Citation[];
  onOpenCitation: (citation: Citation) => void;
}) {
  const chunkCount = pipeline
    .filter((event) => event.stage === 'retrieval')
    .reduce((total, event) => total + ((event.data.matches as unknown[] | undefined)?.length ?? 0), 0);

  if (pipeline.length === 0 && sources.length === 0) {
    return null;
  }

  return (
    <div className="mt-4 space-y-3">
      {pipeline.length > 0 && (
        <CollapsibleMetaSection
          badge={`${chunkCount} chunks`}
          icon={<Microscope size={14} />}
          title="Inspect pipeline"
        >
          <PipelineTrace events={pipeline} />
        </CollapsibleMetaSection>
      )}

      {citations.length > 0 ? (
        <CollapsibleMetaSection badge={`${citations.length}`} icon={<FileSearch size={14} />} title="Sources">
          <CitationList citations={citations} onOpen={onOpenCitation} />
        </CollapsibleMetaSection>
      ) : sources.length > 0 && (
        <CollapsibleMetaSection
          badge={`${sources.length}`}
          icon={<FileSearch size={14} />}
          title="Sources"
        >
          <SourceList sources={sources} pipeline={pipeline} />
        </CollapsibleMetaSection>
      )}
    </div>
  );
}

// Live progress shown while the answer is being generated: one compact line per step, the last few visible
const VISIBLE_STEPS = 3;

function ProcessRow({ item, done }: { item: ProcessItem; done: boolean }) {
  const [open, setOpen] = useState(false);

  if (item.kind === 'thinking') {
    return (
      <li className="flex items-center gap-2 px-1.5 py-1 text-xs text-zinc-500 dark:text-zinc-400">
        {done ? <Check size={12} className="shrink-0 text-emerald-500" /> : <Loader2 size={12} className="shrink-0 animate-spin text-blue-500" />}
        <span className={done ? '' : 'text-zinc-700 dark:text-zinc-200'}>{item.name}</span>
      </li>
    );
  }

  const { label, icon: Icon } = toolInfo(item.name);
  const call = describeToolCall(item.name, item.input);
  const title = resultTitle(item);
  const summary = item.done && item.result !== undefined ? summarizeToolCall(item) : null;

  return (
    <li>
      <button
        onClick={() => setOpen((o) => !o)}
        disabled={!item.result}
        title={item.input}
        className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-xs transition-colors enabled:hover:bg-white disabled:cursor-default dark:enabled:hover:bg-zinc-800/70"
      >
        {done ? <Check size={12} className="shrink-0 text-emerald-500" /> : <Loader2 size={12} className="shrink-0 animate-spin text-amber-500" />}
        <Icon size={12} className="shrink-0 text-zinc-400" />
        <span className="shrink-0 font-medium text-zinc-700 dark:text-zinc-200">{label}</span>
        <span className="min-w-0 truncate text-zinc-500 dark:text-zinc-400">{title ?? call.text}</span>
        {call.tags.map((tag) => (
          <span
            key={tag}
            className="hidden max-w-[9rem] shrink-0 truncate rounded bg-zinc-200/70 px-1.5 text-[10px] text-zinc-500 sm:inline dark:bg-zinc-700/60 dark:text-zinc-300"
          >
            {tag}
          </span>
        ))}
        <span className="ml-auto flex shrink-0 items-center gap-1.5 pl-2 text-[11px] tabular-nums text-zinc-400">
          {summary && (
            <span className={summary.error ? 'text-amber-600 dark:text-amber-400' : ''}>{summary.text}</span>
          )}
          {item.ms !== undefined && <span>· {formatDuration(item.ms)}</span>}
        </span>
      </button>
      {open && item.result && (
        <pre className="mb-1 ml-9 mr-1.5 max-h-40 overflow-auto whitespace-pre-wrap rounded-md border border-zinc-200 bg-white px-2 py-1.5 text-[11px] leading-relaxed text-zinc-600 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-300">
          {item.result}
        </pre>
      )}
    </li>
  );
}

// What happens before the answer arrives: the last VISIBLE_STEPS steps, all of them on demand
// (the finished answer has "Inspect pipeline" instead)
function LiveProgress({ steps }: { steps: Step[] }) {
  const [expanded, setExpanded] = useState(false);
  const items = getProcessItems(steps);
  const toolCount = items.filter((item) => item.kind === 'tool').length;

  if (items.length === 0) {
    return null;
  }

  const hidden = expanded ? 0 : Math.max(0, items.length - VISIBLE_STEPS);

  return (
    // Fixed width: the bubble would otherwise resize with every new line
    <section className="mb-4 w-[40rem] max-w-full rounded-xl border border-zinc-200 bg-zinc-50/70 dark:border-zinc-700 dark:bg-zinc-900/40">
      <div className="flex items-center gap-2 px-3 py-1.5">
        <Loader2 size={12} className="animate-spin text-zinc-400" />
        <span className="text-[11px] font-semibold uppercase tracking-[0.2em] text-zinc-500 dark:text-zinc-400">Process</span>
        {toolCount > 0 && (
          <span className="rounded-full border border-zinc-200 bg-white px-2 py-0.5 text-[10px] font-medium text-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-300">
            {plural(toolCount, 'tool call')}
          </span>
        )}
        {items.length > VISIBLE_STEPS && (
          <button
            onClick={() => setExpanded((e) => !e)}
            className="ml-auto flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-zinc-500 hover:bg-zinc-100 hover:text-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
          >
            {expanded ? 'Show less' : `Show all ${items.length}`}
            {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </button>
        )}
      </div>
      <ol className={`border-t border-zinc-200 px-1.5 py-1 dark:border-zinc-700 ${expanded ? 'max-h-80 overflow-y-auto' : ''}`}>
        {hidden > 0 && (
          <li>
            <button
              onClick={() => setExpanded(true)}
              className="w-full px-1.5 py-0.5 text-left text-[11px] text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300"
            >
              + {hidden} earlier step{hidden > 1 ? 's' : ''}
            </button>
          </li>
        )}
        {items.slice(hidden).map((item, offset) => {
          const index = hidden + offset;
          // A status step is over once anything follows it
          const done = item.kind === 'thinking' ? item.done || index < items.length - 1 : item.done;
          return <ProcessRow key={index} item={item} done={done} />;
        })}
      </ol>
    </section>
  );
}

function AssistantBubble({
  message,
  isStreaming,
  onCopy,
  copied,
}: {
  message: Message;
  isStreaming: boolean;
  onCopy: () => void;
  copied: boolean;
}) {
  const { body, sources } = parseAssistantContent(message.content);
  const hasBody = Boolean(body.trim());
  const citations = getCitations(message.pipeline ?? []);
  const [openCitation, setOpenCitation] = useState<Citation | null>(null);
  // Answer still being generated on the server (the user left and came back): refreshed by polling
  const inBackground = !isStreaming && message.status === 'streaming';
  // Agent answers saved mid-run: their trace already holds the tool calls made so far
  const steps = inBackground ? stepsFromTrace(message.pipeline ?? []) : message.steps ?? [];
  const showProgress = (isStreaming || inBackground) && !hasBody && steps.length > 0;

  return (
    <div className="relative max-w-[85%] rounded-2xl border border-zinc-200 bg-white px-5 py-3 shadow-sm dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100">
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-xs font-bold uppercase tracking-wider opacity-70">Pyrmit</p>
        {message.content && (
          <button
            onClick={onCopy}
            className="rounded-lg p-1.5 text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-700 dark:hover:text-zinc-300"
            title="Copy to clipboard"
          >
            {copied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
          </button>
        )}
      </div>

      {showProgress && <LiveProgress steps={steps} />}
      {inBackground && hasBody && (
        <div className="mb-2 flex items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
          <Loader2 size={12} className="animate-spin" />
          Still generating, this updates automatically
        </div>
      )}

      {hasBody ? (
        <div className="text-sm leading-relaxed prose prose-sm dark:prose-invert max-w-none">
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <CitedMarkdown body={body} citations={citations} onOpen={setOpenCitation} />
          </div>
        </div>
      ) : (isStreaming || inBackground) && !showProgress && (
        // Before the first step arrives (the progress panel shows the rest)
        <div className="flex items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
          <Loader2 size={14} className="animate-spin" />
          {inBackground ? 'Still generating, this updates automatically' : 'Starting'}
        </div>
      )}

      {!isStreaming && !inBackground && (
        <AnswerDetails
          sources={sources}
          pipeline={message.pipeline ?? []}
          citations={citations}
          onOpenCitation={setOpenCitation}
        />
      )}
      {openCitation && <SourceViewer citation={openCitation} onClose={() => setOpenCitation(null)} />}
    </div>
  );
}

export default function Chat({ sessionId, onSessionCreated, user }: ChatProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [mapOpen, setMapOpen] = useState(false);
  // The chat's pinned place: the pin and, once looked up, its label (kept apart so a label never moves the pin)
  const [pin, setPin] = useState<Pin | null>(null);
  const [pinLabel, setPinLabel] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const pendingSessionIdRef = useRef<string | null>(null);
  // Session we just created ourselves: its messages are already in state (with
  // live-only pipeline data), so the history refetch must not overwrite them.
  const createdSessionIdRef = useRef<string | null>(null);
  // The in-flight stream and the session it belongs to: opening another chat aborts the local stream only;
  // the server keeps generating and saving the answer in the history.
  const abortRef = useRef<AbortController | null>(null);
  const streamSessionRef = useRef<string | null>(null);
  const sessionIdRef = useRef<string | null>(sessionId);
  sessionIdRef.current = sessionId;

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const clearPin = () => {
    setPin(null);
    setPinLabel(null);
  };

  const movePin = (next: Pin) => {
    setPin(next);
    setPinLabel(null);
  };

  const loadHistory = (id: string, showLoading: boolean) => {
    if (showLoading) setLoading(true);
    authFetch(`/api/sessions/${id}`)
      .then((res) => res.json())
      .then((data: Message[]) => {
        if (sessionIdRef.current !== id) return; // the user moved to another chat meanwhile
        setMessages(data.map((msg) => ({ ...msg, pipeline: msg.trace ?? undefined })));
        if (showLoading) {
          // Opening a chat brings back the place its latest answer was about (ADR-0004)
          const place = placeFromHistory(data.map((msg) => msg.trace));
          setPin(place ? { lat: place.lat, lon: place.lon } : null);
          setPinLabel(place?.label ?? null);
        }
      })
      .catch((err) => console.error('Failed to fetch history', err))
      .finally(() => {
        if (showLoading) setLoading(false);
      });
  };

  useEffect(() => {
    if (abortRef.current && sessionId !== streamSessionRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
      setStreaming(false);
    }
    if (sessionId && sessionId === createdSessionIdRef.current) {
      createdSessionIdRef.current = null;
      return;
    }
    if (sessionId) {
      loadHistory(sessionId, true);
    } else {
      setMessages([]);
      setPin(null); // a new chat has no place yet
      setPinLabel(null);
    }
     
  }, [sessionId]);

  // An answer generated in the background (the user left during streaming): refresh until it is finished
  const hasBackgroundAnswer = messages.some((msg) => msg.status === 'streaming');
  useEffect(() => {
    if (streaming || !sessionId || !hasBackgroundAnswer) return;
    const timer = setTimeout(() => loadHistory(sessionId, false), 2000);
    return () => clearTimeout(timer);
     
  }, [messages, streaming, sessionId, hasBackgroundAnswer]);

  const handleCopy = async (content: string, index: number) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 2000);
    } catch (err) {
      console.error('Failed to copy', err);
    }
  };

  const sendMessage = async (e: FormEvent) => {
    e.preventDefault();
    const trimmedInput = input.trim();
    if (!trimmedInput) return;

    const userMsg: Message = { role: 'user', content: trimmedInput };
    const newHistory = [...messages, userMsg];
    const placeholder: Message = { role: 'assistant', content: '', steps: [] };
    setMessages([...newHistory, placeholder]);
    setInput('');
    setLoading(true);
    setStreaming(true);
    pendingSessionIdRef.current = null;
    const controller = new AbortController();
    abortRef.current = controller;
    streamSessionRef.current = sessionId;
    let announced = false;
    let gotDone = false;
    let stalled = false;
    let watchdog: ReturnType<typeof setInterval> | undefined;
    // A new chat shows up in the sidebar as soon as the server created it, not only at the end
    const announceSession = (createdSessionId: string | null | undefined) => {
      if (sessionId || announced || !createdSessionId) return;
      announced = true;
      streamSessionRef.current = createdSessionId;
      createdSessionIdRef.current = createdSessionId;
      onSessionCreated(createdSessionId);
    };

    try {
      const res = await authFetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: newHistory, session_id: sessionId,
                               place: pin ? { ...pin, label: pinLabel } : null }),
        signal: controller.signal,
      });

      if (!res.ok) throw new Error(`Request failed: ${res.status}`);
      if (!res.body) throw new Error('No response body');

      setLoading(false);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      const updateLast = (updater: (msg: Message) => Message) => {
        setMessages((prev) => {
          if (prev.length === 0) {
            return prev;
          }
          const updated = [...prev];
          updated[updated.length - 1] = updater(updated[updated.length - 1]);
          return updated;
        });
      };

      const handleStreamEvent = (event: StreamEvent) => {
        switch (event.type) {
          case 'thinking':
            updateLast((msg) => ({
              ...msg,
              steps: [...(msg.steps ?? []), { type: 'thinking', label: event.label, done: false }],
            }));
            break;

          case 'tool_call':
            updateLast((msg) => ({
              ...msg,
              steps: [
                ...(msg.steps ?? []).map((s) =>
                  s.type === 'thinking' && !s.done ? { ...s, done: true } : s
                ),
                { type: 'tool_call', name: event.name, input: event.input, done: false },
              ],
            }));
            break;

          case 'tool_result':
            updateLast((msg) => {
              // Results of parallel calls arrive in call order: close the oldest open call of that tool
              const steps = msg.steps ?? [];
              const open = steps.findIndex((s) => s.type === 'tool_call' && s.name === event.name && !s.done);
              return {
                ...msg,
                steps: [
                  ...steps.map((s, i) => (i === open ? { ...s, done: true } : s)),
                  {
                    type: 'tool_result', name: event.name, result: event.result,
                    chunks: event.chunks, ms: event.ms, done: true,
                  },
                ],
              };
            });
            break;

          case 'pipeline':
            if (event.stage && event.data) {
              const pipelineEvent: PipelineEvent = { stage: event.stage, data: event.data };
              updateLast((msg) => ({
                ...msg,
                pipeline: [...(msg.pipeline ?? []), pipelineEvent],
              }));
            }
            break;

          case 'response.output_text.delta':
            if (event.delta) {
              updateLast((msg) => ({
                ...msg,
                steps: (msg.steps ?? []).map((s) => ({ ...s, done: true })),
                content: msg.content + event.delta,
              }));
            }
            break;

          case 'token':
            if (event.token) {
              updateLast((msg) => ({
                ...msg,
                steps: (msg.steps ?? []).map((s) => ({ ...s, done: true })),
                content: msg.content + event.token,
              }));
            }
            break;

          case 'response.completed':
            updateLast((msg) => ({
              ...msg,
              steps: (msg.steps ?? []).map((s) => ({ ...s, done: true })),
            }));
            break;

          case 'session_id':
            pendingSessionIdRef.current = event.session_id ?? null;
            announceSession(event.session_id);
            break;

          case 'done':
            gotDone = true;
            announceSession(event.session_id ?? pendingSessionIdRef.current);
            pendingSessionIdRef.current = null;
            break;

          case 'error':
            console.error('Stream error:', event.message);
            updateLast((msg) => ({
              ...msg,
              content: msg.content || `Error: ${event.message}`,
            }));
            break;
        }
      };

      // The server sends a keep-alive every 10 s: silence means the connection died without closing (a proxy
      // timeout), and the reader would wait forever
      let lastData = Date.now();
      watchdog = setInterval(() => {
        if (Date.now() - lastData > STREAM_STALL_MS) {
          stalled = true;
          controller.abort();
        }
      }, 5000);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        lastData = Date.now();

        buffer += decoder.decode(value, { stream: true });
        const parsed = extractSseEvents(buffer);
        buffer = parsed.remainder;

        for (const event of parsed.events) {
          handleStreamEvent(event);
        }
      }

      buffer += decoder.decode();
      const finalParsed = extractSseEvents(buffer);
      for (const event of finalParsed.events) {
        handleStreamEvent(event);
      }
    } catch (error) {
      // Aborted because the user opened another chat: the server finishes the answer in the history
      if (controller.signal.aborted && !stalled) return;
      console.error('Error sending message:', error);
      // The server keeps generating once it has the session: show the saved answer instead
      if (!streamSessionRef.current) setMessages((prev) => prev.slice(0, -1));
    } finally {
      clearInterval(watchdog);
      if (abortRef.current === controller) {
        abortRef.current = null;
        setLoading(false);
        setStreaming(false);
      }
      pendingSessionIdRef.current = null;
      // Stream cut before "done": reload the session, its message is polled until the server finishes
      const streamedSession = streamSessionRef.current;
      if (!gotDone && streamedSession && sessionIdRef.current === streamedSession && (stalled || !controller.signal.aborted)) {
        loadHistory(streamedSession, false);
      }
    }
  };
  const lastIdx = messages.length - 1;

  return (
    <div className="flex h-full w-full">
    <div className="flex flex-col h-full flex-1 min-w-0 relative">
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto p-4 space-y-6 pb-32 pt-10">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center text-center p-8 mt-20">
              <div className="opacity-50 flex flex-col items-center mb-6">
                <div className="w-24 h-24 relative rounded-full overflow-hidden mb-4 shadow-sm">
                  <Image src="/pyrmit_middle.jpg" alt="Pyrmit Logo" fill sizes="96px" className="object-cover" />
                </div>
                <h2 className="text-2xl font-bold mb-2">Pyrmit Agent</h2>
                <p className="max-w-md">I can help you navigate building permits, zoning laws, and construction regulations.</p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg">
                {EXAMPLE_PROMPTS.map((prompt, i) => (
                  <button
                    key={i}
                    onClick={() => setInput(prompt)}
                    className="text-left px-4 py-3 text-sm rounded-xl border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div
              key={msg.id ?? `${msg.role}-${msg.created_at ?? i}`}
              className={`group flex items-start gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              {msg.role !== 'user' && (
                <div className="w-8 h-8 relative rounded-full overflow-hidden flex-shrink-0 mt-1 border border-zinc-200 dark:border-zinc-700">
                  <Image src="/pyrmit_middle.jpg" alt="Pyrmit" fill sizes="36px" className="object-cover" />
                </div>
              )}

              {msg.role === 'user' ? (
                <div className="relative max-w-[85%] rounded-2xl px-5 py-3 shadow-sm bg-blue-600 text-white">
                  <div className="text-sm leading-relaxed whitespace-pre-wrap">{msg.content}</div>
                </div>
              ) : (
                <AssistantBubble
                  copied={copiedIndex === i}
                  isStreaming={streaming && i === lastIdx}
                  message={msg}
                  onCopy={() => handleCopy(msg.content, i)}
                />
              )}

              {msg.role === 'user' && (
                <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900 flex items-center justify-center text-blue-600 dark:text-blue-300 font-bold text-xs flex-shrink-0 mt-1">
                  {user?.name?.charAt(0).toUpperCase() || 'U'}
                </div>
              )}
            </div>
          ))}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <div className="absolute bottom-0 left-0 w-full bg-gradient-to-t from-white via-white to-transparent dark:from-zinc-900 dark:via-zinc-900 pt-10 pb-6 px-4">
        <div className="max-w-3xl mx-auto">
          {pin && (
            <div className="mb-2">
              <PlaceChip place={{ ...pin, label: pinLabel }} onOpen={() => setMapOpen(true)}
                         onClear={clearPin} />
            </div>
          )}
          <form onSubmit={sendMessage} className="relative shadow-lg rounded-xl">
            <button
              type="button"
              onClick={() => setMapOpen((open) => !open)}
              aria-label={mapOpen ? 'Hide map' : 'Open map'}
              aria-pressed={mapOpen}
              className={`absolute left-2 top-2 bottom-2 px-2.5 rounded-lg transition-transform duration-100 active:scale-95 flex items-center justify-center ${mapOpen ? 'bg-blue-50 text-blue-600 dark:bg-blue-950/60 dark:text-blue-300' : 'text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-700'}`}
            >
              <MapPin size={18} />
            </button>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about building permits..."
              className="w-full p-4 pl-14 pr-24 rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
              disabled={loading || streaming}
            />
            <button
              type="submit"
              disabled={loading || streaming || !input.trim()}
              className="absolute right-2 top-2 bottom-2 px-4 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 disabled:bg-zinc-300 dark:disabled:bg-zinc-700 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
            >
              {(loading || streaming) && <Loader2 size={14} className="animate-spin" />}
              Send
            </button>
          </form>
          <p className="text-center text-xs text-zinc-400 dark:text-zinc-500 mt-3">
            Pyrmit can make mistakes. Verify important information.
          </p>
        </div>
      </div>
    </div>
    {mapOpen && (
      <PlacePanel pin={pin} onPinChange={movePin} onClose={() => setMapOpen(false)}
                  onProfile={(profile) => setPinLabel(placeLabel(profile))} />
    )}
    </div>
  );
}
