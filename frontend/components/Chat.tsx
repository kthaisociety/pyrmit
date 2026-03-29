'use client';

import { useState, useEffect, FormEvent, useRef } from 'react';
import Image from 'next/image';
import ReactMarkdown from 'react-markdown';
import { Copy, Check } from 'lucide-react';
import { authFetch } from '@/lib/auth';

interface Message {
  role: string;
  content: string;
  session_id?: string;
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

export default function Chat({ sessionId, onSessionCreated, user }: ChatProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    if (sessionId) {
      setLoading(true);
      authFetch(`${API_URL}/api/sessions/${sessionId}`)
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
  }, [API_URL, sessionId]);

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

    try {
      const res = await authFetch(`${API_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: newHistory,
          session_id: sessionId
        }),
      });

      if (!res.ok) throw new Error('Failed to send message');

      const data: Message = await res.json();
      setMessages((prev) => [...prev, data]);

      // If we started a new session, notify parent
      if (!sessionId && data.session_id) {
        onSessionCreated(data.session_id);
      }
    } catch (error) {
      console.error('Error sending message:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full w-full relative">
      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto p-4 space-y-6 pb-32 pt-10">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center text-center p-8 mt-20">
              <div className="opacity-50 flex flex-col items-center mb-6">
                <div className="w-24 h-24 relative rounded-full overflow-hidden mb-4 shadow-sm">
                  <Image
                    src="/pyrmit_middle.jpg"
                    alt="Pyrmit Logo"
                    fill
                    className="object-cover"
                  />
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
              className={`group flex items-start gap-3 ${
                msg.role === 'user' ? 'justify-end' : 'justify-start'
              }`}
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
                {msg.role === 'user' ? (
                  <div className="text-sm leading-relaxed whitespace-pre-wrap">{msg.content}</div>
                ) : (
                  <ReactMarkdown className="text-sm leading-relaxed prose prose-sm dark:prose-invert max-w-none">
                    {msg.content}
                  </ReactMarkdown>
                )}
                {msg.role !== 'user' && (
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

          {loading && (
            <div className="flex items-start gap-3 justify-start">
              <div className="w-8 h-8 relative rounded-full overflow-hidden flex-shrink-0 mt-1 border border-zinc-200 dark:border-zinc-700">
                <Image src="/pyrmit_middle.jpg" alt="Pyrmit" fill className="object-cover" />
              </div>
              <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-2xl px-5 py-4 shadow-sm">
                <div className="flex space-x-2 items-center h-4">
                  <div className="w-2 h-2 bg-zinc-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                  <div className="w-2 h-2 bg-zinc-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                  <div className="w-2 h-2 bg-zinc-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input Area */}
      <div className="absolute bottom-0 left-0 w-full bg-gradient-to-t from-white via-white to-transparent dark:from-zinc-900 dark:via-zinc-900 pt-10 pb-6 px-4">
        <div className="max-w-3xl mx-auto">
          <form onSubmit={sendMessage} className="relative shadow-lg rounded-xl">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about building permits..."
              className="w-full p-4 pr-24 rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
              disabled={loading}
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="absolute right-2 top-2 bottom-2 px-4 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 disabled:bg-zinc-300 dark:disabled:bg-zinc-700 disabled:cursor-not-allowed transition-colors flex items-center justify-center"
            >
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
