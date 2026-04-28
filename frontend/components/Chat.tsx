'use client';

import { useState, useEffect, FormEvent, ReactNode, useRef } from 'react';
import Image from 'next/image';
import ReactMarkdown from 'react-markdown';
import {
  Brain,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  FileSearch,
  Loader2,
  Wrench,
} from 'lucide-react';
import { authFetch } from '@/lib/auth';

interface Message {
  id?: number;
  role: string;
  content: string;
  session_id?: string;
  created_at?: string;
  steps?: Step[];
}

interface Step {
  type: 'thinking' | 'tool_call' | 'tool_result';
  label?: string;   // thinking
  name?: string;    // tool_call / tool_result
  input?: string;   // tool_call
  result?: string;  // tool_result
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
  message?: string;
}

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

interface ToolTrace {
  name: string;
  input?: string;
  result?: string;
  done: boolean;
}

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
    .map((line) => line.slice(2).trim())
    .filter(Boolean);

  return { body, sources };
}

function getReasoningSteps(steps: Step[]): string[] {
  return steps
    .filter((step) => step.type === 'thinking')
    .map((step) => step.label?.trim())
    .filter((label): label is string => Boolean(label));
}

function getToolTraces(steps: Step[]): ToolTrace[] {
  const traces: ToolTrace[] = [];

  for (const step of steps) {
    if (step.type === 'tool_call') {
      traces.push({
        name: step.name || 'tool',
        input: step.input,
        done: step.done,
      });
      continue;
    }

    if (step.type === 'tool_result') {
      const existing = [...traces].reverse().find((trace) => trace.name === step.name && !trace.result);
      if (existing) {
        existing.result = step.result;
        existing.done = true;
      } else {
        traces.push({
          name: step.name || 'tool',
          result: step.result,
          done: true,
        });
      }
    }
  }

  return traces;
}

function formatTraceValue(value?: string): string {
  if (!value) {
    return '';
  }

  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

function humanizeToolName(name?: string): string {
  switch (name) {
    case 'embed_query':
      return 'Preparing your question';
    case 'retrieve_law_chunks':
      return 'Checking relevant law';
    case 'retrieve_document_chunks':
      return 'Checking planning documents';
    case 'law_agent':
      return 'Reviewing legal requirements';
    case 'document_agent':
      return 'Reviewing local plan material';
    default:
      return (name || 'Working')
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (char) => char.toUpperCase());
  }
}

function summarizeToolResult(tool: ToolTrace): string {
  const result = formatTraceValue(tool.result);

  switch (tool.name) {
    case 'retrieve_law_chunks':
    case 'retrieve_document_chunks':
      return result ? `Found ${result.replace('chunks', 'relevant sections')}.` : 'Looking through relevant sections.';
    case 'embed_query':
      return 'Organizing the question so it can be matched against the right material.';
    case 'law_agent':
      return tool.done ? 'Legal review finished.' : 'Working through the legal side.';
    case 'document_agent':
      return tool.done ? 'Planning document review finished.' : 'Working through the planning material.';
    default:
      return tool.done ? 'Step completed.' : 'Working on this step.';
  }
}

function TraceValue({ value }: { value?: string }) {
  if (!value) {
    return null;
  }

  const formatted = formatTraceValue(value);
  const isCompact = !formatted.includes('\n') && formatted.length < 90;

  if (isCompact) {
    return (
      <div className="inline-flex max-w-full rounded-full border border-zinc-200/80 bg-white/80 px-2.5 py-1 text-[11px] text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900/70 dark:text-zinc-300">
        <span className="truncate">{formatted}</span>
      </div>
    );
  }

  return (
    <pre className="overflow-x-auto rounded-2xl border border-zinc-200/80 bg-zinc-950 px-3 py-2 text-[11px] leading-relaxed text-zinc-100 dark:border-zinc-700">
      <code>{formatted}</code>
    </pre>
  );
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

function AssistantTelemetry({
  steps,
  sources,
  streaming,
}: {
  steps: Step[];
  sources: string[];
  streaming: boolean;
}) {
  const reasoning = getReasoningSteps(steps);
  const tools = getToolTraces(steps);

  if (reasoning.length === 0 && tools.length === 0 && sources.length === 0) {
    return null;
  }

  return (
    <div className="mb-4 space-y-3">
      {sources.length > 0 && (
        <CollapsibleMetaSection
          badge={`${sources.length}`}
          icon={<FileSearch size={14} />}
          title="Sources"
        >
          <div className="flex flex-wrap gap-2 pt-1">
            {sources.map((source, index) => (
              <div
                key={`${source}-${index}`}
                className="rounded-full border border-zinc-200 bg-white px-2.5 py-1 text-[11px] text-zinc-600 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-300"
              >
                {source}
              </div>
            ))}
          </div>
        </CollapsibleMetaSection>
      )}

      {reasoning.length > 0 && (
        <CollapsibleMetaSection
          badge={streaming ? 'Thinking' : `${reasoning.length} steps`}
          defaultOpen={streaming}
          forceOpen={streaming}
          icon={streaming ? <Loader2 size={14} className="animate-spin" /> : <Brain size={14} />}
          title="Reasoning"
        >
          <div className="space-y-2 pt-1">
            {reasoning.map((item, index) => (
              <div
                key={`${item}-${index}`}
                className="flex items-start gap-3 rounded-xl bg-white px-3 py-2.5 dark:bg-zinc-950/70"
              >
                <div className="mt-0.5 flex size-5 items-center justify-center rounded-full bg-blue-100 text-[10px] font-semibold text-blue-700 dark:bg-blue-950 dark:text-blue-300">
                  {index + 1}
                </div>
                <div className="min-w-0 text-sm leading-relaxed text-zinc-700 dark:text-zinc-200">
                  {item}
                </div>
              </div>
            ))}
          </div>
        </CollapsibleMetaSection>
      )}

      {tools.length > 0 && (
        <CollapsibleMetaSection
          badge={streaming ? 'Working' : `${tools.length} steps`}
          defaultOpen={streaming}
          forceOpen={streaming}
          icon={<Wrench size={14} />}
          title="Process"
        >
          <div className="space-y-2 pt-1">
            {tools.map((tool, index) => (
              <div
                key={`${tool.name}-${index}`}
                className="rounded-xl bg-white px-3 py-2.5 dark:bg-zinc-950/70"
              >
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex size-7 items-center justify-center rounded-lg bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                    {tool.done ? <CheckCircle2 size={13} /> : <Loader2 size={13} className="animate-spin" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-zinc-800 dark:text-zinc-100">{humanizeToolName(tool.name)}</div>
                    <div className="mt-1 text-sm leading-relaxed text-zinc-500 dark:text-zinc-400">
                      {summarizeToolResult(tool)}
                    </div>
                  </div>
                  <div className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                    tool.done
                      ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300'
                      : 'bg-amber-100 text-amber-700 dark:bg-amber-950/60 dark:text-amber-300'
                  }`}>
                    {tool.done ? 'Done' : 'Working'}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CollapsibleMetaSection>
      )}
    </div>
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
  const steps = message.steps ?? [];

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

      <AssistantTelemetry sources={sources} steps={steps} streaming={isStreaming} />

      {hasBody ? (
        <div className="text-sm leading-relaxed prose prose-sm dark:prose-invert max-w-none">
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <ReactMarkdown>{body}</ReactMarkdown>
          </div>
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-zinc-300 px-4 py-4 dark:border-zinc-700">
          <div className="flex items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
            <Loader2 size={14} className="animate-spin" />
            Writing the answer
          </div>
        </div>
      )}
    </div>
  );
}

export default function Chat({ sessionId, onSessionCreated, user }: ChatProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const pendingSessionIdRef = useRef<string | null>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    if (sessionId) {
      setLoading(true);
      authFetch(`/api/sessions/${sessionId}`)
        .then((res) => res.json())
        .then((data: Message[]) => {
          setMessages(data);
          setLoading(false);
        })
        .catch((err) => {
          console.error('Failed to fetch history', err);
          setLoading(false);
        });
    } else {
      setMessages([]);
    }
  }, [sessionId]);

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

    try {
      const res = await authFetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: newHistory, session_id: sessionId }),
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
            updateLast((msg) => ({
              ...msg,
              steps: [
                ...(msg.steps ?? []).map((s) =>
                  s.type === 'tool_call' && s.name === event.name && !s.done
                    ? { ...s, done: true }
                    : s
                ),
                { type: 'tool_result', name: event.name, result: event.result, done: true },
              ],
            }));
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
            break;

          case 'done':
            if (!sessionId) {
              const createdSessionId = event.session_id ?? pendingSessionIdRef.current;
              if (createdSessionId) {
                onSessionCreated(createdSessionId);
              }
            }
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

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

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
      console.error('Error sending message:', error);
      setMessages((prev) => prev.slice(0, -1));
    } finally {
      setLoading(false);
      setStreaming(false);
      pendingSessionIdRef.current = null;
    }
  };
  const lastIdx = messages.length - 1;

  return (
    <div className="flex flex-col h-full w-full relative">
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
          <form onSubmit={sendMessage} className="relative shadow-lg rounded-xl">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about building permits..."
              className="w-full p-4 pr-24 rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
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
  );
}
