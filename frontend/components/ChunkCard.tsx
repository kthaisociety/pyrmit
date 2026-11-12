'use client';

import { ReactNode, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

export interface ChunkCardProps {
  source: string;
  chunkIndex?: number | null;
  distance?: number | null;
  content: string;
  meta?: string[];
  rank?: number;
  defaultOpen?: boolean;
  actions?: ReactNode; // shown under the header, open or not (e.g. links to the original document)
  // Sentences of `content` to underline in the open card (<u title="Supports a claim in the answer">), issue #84.
  // Matched regardless of whitespace (runs of spaces and line breaks compare equal); a sentence not found in
  // `content` is skipped without an error. The collapsed preview is never underlined.
  underline?: string[];
}

// Cosine distance: 0 = identical, 1 = unrelated. Colour bands are a rough visual aid only,
// calibrated on text-embedding-3-large where good matches typically land around 0.5–0.6.
function distanceTone(distance: number): string {
  if (distance < 0.55) return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300';
  if (distance < 0.65) return 'bg-amber-100 text-amber-700 dark:bg-amber-950/60 dark:text-amber-300';
  return 'bg-red-100 text-red-700 dark:bg-red-950/60 dark:text-red-300';
}

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// The [start, end) ranges of `content` that hold one of the sentences, whitespace-insensitive, merged when they
// overlap
function underlineRanges(content: string, sentences: string[]): [number, number][] {
  const ranges: [number, number][] = [];
  for (const sentence of sentences) {
    const words = sentence.trim().split(/\s+/).filter(Boolean);
    if (words.length === 0) continue;
    const match = new RegExp(words.map(escape).join('\\s+')).exec(content);
    if (match) ranges.push([match.index, match.index + match[0].length]);
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const [start, end] of ranges) {
    const last = merged[merged.length - 1];
    if (last && start <= last[1]) last[1] = Math.max(last[1], end);
    else merged.push([start, end]);
  }
  return merged;
}

function Underlined({ content, sentences }: { content: string; sentences: string[] }) {
  const parts: ReactNode[] = [];
  let pos = 0;
  for (const [start, end] of underlineRanges(content, sentences)) {
    parts.push(content.slice(pos, start));
    parts.push(
      <u key={start} title="Supports a claim in the answer" className="decoration-emerald-500 decoration-2 underline-offset-2">
        {content.slice(start, end)}
      </u>,
    );
    pos = end;
  }
  parts.push(content.slice(pos));
  return <>{parts}</>;
}

export default function ChunkCard({
  source,
  chunkIndex,
  distance,
  content,
  meta = [],
  rank,
  defaultOpen = false,
  actions,
  underline = [],
}: ChunkCardProps) {
  const [open, setOpen] = useState(defaultOpen);
  const preview = content.replace(/\s+/g, ' ').slice(0, 220);

  return (
    <div className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-950/70">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-start gap-2 px-3 py-2 text-left"
      >
        <span className="mt-0.5 text-zinc-400">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
            {rank !== undefined && (
              <span className="font-semibold text-zinc-400">#{rank}</span>
            )}
            <span className="truncate font-medium text-zinc-800 dark:text-zinc-100">{source}</span>
            {chunkIndex !== undefined && chunkIndex !== null && (
              <span className="rounded-full bg-zinc-100 px-1.5 py-0.5 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
                chunk {chunkIndex}
              </span>
            )}
            {meta.map((item) => (
              <span
                key={item}
                className="rounded-full bg-zinc-100 px-1.5 py-0.5 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
              >
                {item}
              </span>
            ))}
            {distance !== undefined && distance !== null && (
              <span className={`rounded-full px-1.5 py-0.5 font-mono ${distanceTone(distance)}`} title="Cosine distance (lower = closer)">
                d={distance.toFixed(3)}
              </span>
            )}
          </div>
          {!open && (
            <p className="mt-1 line-clamp-2 text-xs text-zinc-500 dark:text-zinc-400">{preview}</p>
          )}
        </div>
      </button>
      {actions && <div className="flex flex-wrap items-center gap-1.5 px-3 pb-2 pl-8">{actions}</div>}
      {open && (
        <pre className="max-h-96 overflow-auto whitespace-pre-wrap border-t border-zinc-200 px-3 py-2 font-sans text-xs leading-relaxed text-zinc-700 dark:border-zinc-700 dark:text-zinc-200">
          <Underlined content={content} sentences={underline} />
        </pre>
      )}
    </div>
  );
}
