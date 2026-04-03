'use client';

import { useState, useEffect, FormEvent, useRef } from 'react';
import Image from 'next/image';
import ReactMarkdown from 'react-markdown';
import { Copy, Check, ChevronDown, ChevronRight, Loader2, Wrench, Brain, CheckCircle2 } from 'lucide-react';
import { authFetch } from '@/lib/auth';

interface Message {
  role: string;
  content: string;
  session_id?: string;
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

function StepIndicator({ steps, streaming }: { steps: Step[]; streaming: boolean }) {
  const [open, setOpen] = useState(true);

  // Auto-collapse when streaming is done and content has appeared
  useEffect(() => {
    if (!streaming) {
      const timer = setTimeout(() => setOpen(false), 1200);
      return () => clearTimeout(timer);
    }
  }, [streaming]);

  if (steps.length === 0) return null;

  // Group tool_call + its tool_result together
  const items: { call: Step; result?: Step }[] = [];
  for (let i = 0; i < steps.length; i++) {
    const s = steps[i];
    if (s.type === 'tool_call') {
      const next = steps[i + 1];
      if (next?.type === 'tool_result' && next.name === s.name) {
        items.push({ call: s, result: next });
        i++;
      } else {
        items.push({ call: s });
      }
    } else if (s.type === 'thinking') {
      items.push({ call: s });
    }
  }

  return (
    <div className="mb-3 rounded-xl border border-zinc-200 dark:border-zinc-700 overflow-hidden text-xs">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-zinc-50 dark:bg-zinc-800/60 hover:bg-zinc-100 dark:hover:bg-zinc-700/60 transition-colors text-zinc-500 dark:text-zinc-400"
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <Brain size={12} />
        <span className="font-medium">
          {streaming ? 'Thinking…' : `${items.length} steps`}
        </span>
        {streaming && (
          <Loader2 size={10} className="ml-auto animate-spin text-blue-400" />
        )}
        {!streaming && (
          <CheckCircle2 size={10} className="ml-auto text-green-500" />
        )}
      </button>

      {open && (
        <div className="divide-y divide-zinc-100 dark:divide-zinc-700/50">
          {items.map((item, i) => {
            const isThinking = item.call.type === 'thinking';
            const isRunning = !item.call.done;

            return (
              <div key={i} className="px-3 py-2 bg-white dark:bg-zinc-900/40 flex items-start gap-2">
                {isThinking ? (
                  <Brain size={11} className="mt-0.5 flex-shrink-0 text-purple-400" />
                ) : (
                  <Wrench size={11} className="mt-0.5 flex-shrink-0 text-blue-400" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-zinc-700 dark:text-zinc-300 truncate">
                      {isThinking ? item.call.label : item.call.name}
                    </span>
                    {isRunning && (
                      <Loader2 size={9} className="animate-spin text-zinc-400 flex-shrink-0" />
                    )}
                    {!isRunning && item.result && (
                      <span className="text-zinc-400 dark:text-zinc-500 truncate">{item.result.result}</span>
                    )}
                  </div>
                  {!isThinking && item.call.input && (
                    <div className="text-zinc-400 dark:text-zinc-500 truncate mt-0.5">{item.call.input}</div>
                  )}
                </div>
              </div>
            );
          })}
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
    if (!input.trim()) return;

    const userMsg: Message = { role: 'user', content: input };
    const newHistory = [...messages, userMsg];
    setMessages(newHistory);
    setInput('');
    setLoading(true);

    // Add streaming placeholder
    const placeholder: Message = { role: 'assistant', content: '', steps: [] };
    setMessages((prev) => [...prev, placeholder]);

    try {
      const res = await authFetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: newHistory, session_id: sessionId }),
      });

      if (!res.ok) throw new Error(`Request failed: ${res.status}`);
      if (!res.body) throw new Error('No response body');

      setLoading(false);
      setStreaming(true);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let notifiedSession = false;

      const updateLast = (updater: (msg: Message) => Message) => {
        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = updater(updated[updated.length - 1]);
          return updated;
        });
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;

          let event: {
            type: string;
            token?: string;
            session_id?: string;
            label?: string;
            name?: string;
            input?: string;
            result?: string;
            message?: string;
          };
          try { event = JSON.parse(raw); } catch { continue; }

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

            case 'token':
              if (event.token) {
                updateLast((msg) => ({
                  ...msg,
                  // Mark all pending steps done when first token arrives
                  steps: (msg.steps ?? []).map((s) => ({ ...s, done: true })),
                  content: msg.content + event.token,
                }));
              }
              break;

            case 'done':
              if (event.session_id && !notifiedSession) {
                notifiedSession = true;
                if (!sessionId) onSessionCreated(event.session_id);
              }
              break;

            case 'error':
              console.error('Stream error:', event.message);
              updateLast((msg) => ({
                ...msg,
                content: msg.content || `Error: ${event.message}`,
              }));
              break;
          }
        }
      }
    } catch (error) {
      console.error('Error sending message:', error);
      setMessages((prev) => prev.slice(0, -1));
    } finally {
      setLoading(false);
      setStreaming(false);
    }
  };

  const isThinking = loading && !streaming;
  const lastIdx = messages.length - 1;

  return (
    <div className="flex flex-col h-full w-full relative">
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto p-4 space-y-6 pb-32 pt-10">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center text-center p-8 mt-20">
              <div className="opacity-50 flex flex-col items-center mb-6">
                <div className="w-24 h-24 relative rounded-full overflow-hidden mb-4 shadow-sm">
                  <Image src="/pyrmit_middle.jpg" alt="Pyrmit Logo" fill className="object-cover" />
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
              key={i}
              className={`group flex items-start gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              {msg.role !== 'user' && (
                <div className="w-8 h-8 relative rounded-full overflow-hidden flex-shrink-0 mt-1 border border-zinc-200 dark:border-zinc-700">
                  <Image src="/pyrmit_middle.jpg" alt="Pyrmit" fill className="object-cover" />
                </div>
              )}

              <div
                className={`relative max-w-[85%] rounded-2xl px-5 py-3 shadow-sm ${
                  msg.role === 'user'
                    ? 'bg-blue-600 text-white'
                    : 'bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-900 dark:text-zinc-100'
                }`}
              >
                <p className="text-xs font-bold mb-1 opacity-70 uppercase tracking-wider">
                  {msg.role === 'user' ? 'You' : 'Pyrmit'}
                </p>

                {msg.role !== 'user' && msg.steps && msg.steps.length > 0 && (
                  <StepIndicator steps={msg.steps} streaming={streaming && i === lastIdx} />
                )}

                {msg.role === 'user' ? (
                  <div className="text-sm leading-relaxed whitespace-pre-wrap">{msg.content}</div>
                ) : msg.content ? (
                  <div className="text-sm leading-relaxed prose prose-sm dark:prose-invert max-w-none">
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                  </div>
                ) : (
                  // No content yet — bouncing cursor inside bubble
                  <span className="inline-block w-1.5 h-4 bg-zinc-400 rounded-sm animate-pulse" />
                )}

                {msg.role !== 'user' && msg.content && (
                  <button
                    onClick={() => handleCopy(msg.content, i)}
                    className="absolute top-2 right-2 p-1.5 rounded-lg opacity-0 group-hover:opacity-100 transition-opacity hover:bg-zinc-100 dark:hover:bg-zinc-700 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300"
                    title="Copy to clipboard"
                  >
                    {copiedIndex === i ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
                  </button>
                )}
              </div>

              {msg.role === 'user' && (
                <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900 flex items-center justify-center text-blue-600 dark:text-blue-300 font-bold text-xs flex-shrink-0 mt-1">
                  {user?.name?.charAt(0).toUpperCase() || 'U'}
                </div>
              )}
            </div>
          ))}

          {/* Dots only during initial fetch before first SSE event */}
          {isThinking && (
            <div className="flex items-start gap-3 justify-start">
              <div className="w-8 h-8 relative rounded-full overflow-hidden flex-shrink-0 mt-1 border border-zinc-200 dark:border-zinc-700">
                <Image src="/pyrmit_middle.jpg" alt="Pyrmit" fill className="object-cover" />
              </div>
              <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-2xl px-5 py-4 shadow-sm">
                <div className="flex space-x-2 items-center h-4">
                  <div className="w-2 h-2 bg-zinc-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <div className="w-2 h-2 bg-zinc-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <div className="w-2 h-2 bg-zinc-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            </div>
          )}
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
