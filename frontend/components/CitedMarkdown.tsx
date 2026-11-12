'use client';

import ReactMarkdown from 'react-markdown';
import type { Citation } from '@/components/SourceViewer';

// "[1]", "[2; 4]", "[1, 3]" -> one markdown link per number (#cite-n), rendered as clickable chips.
// The agent also mixes law references into the group, sometimes nested: "[2; MB 7 kap. 15 §]",
// "[1; MB 7 kap. 15 § [2]]", "[MB 7 kap. 18 c §§ [4] [5]; Ydre's form [1]]". The numbers become chips and the
// references follow in italics. Groups without a number (and markdown links) are left as they are.
const MARK = (n: string) => `\u0000${n}\u0001`; // placeholder for a number found in an inner group
const MARKS = /\u0000(\d+)\u0001/g;
const CHIP = (n: string) => `[${n}](#cite-${n})`;

export function linkCitations(body: string): string {
  // 1. Inner groups of numbers only -> placeholders, so an outer group no longer contains brackets
  const marked = body.replace(/\[(\d{1,3}(?:\s*[;,]\s*\d{1,3})*)\](?!\()/g, (_: string, numbers: string) =>
    numbers.split(/\s*[;,]\s*/).map(MARK).join(''));
  // 2. Outer groups mixing numbers / placeholders and references -> chips + references in italics
  const grouped = marked.replace(/\[([^\[\]\n]{1,300})\](?!\()/g, (whole: string, inner: string) => {
    const numbers: string[] = [];
    const references: string[] = [];
    for (const part of inner.split(/\s*;\s*/)) {
      let rest = part.replace(MARKS, (_: string, n: string) => { numbers.push(n); return ' '; }).trim();
      if (/^\d{1,3}(\s*,\s*\d{1,3})*$/.test(rest)) {
        numbers.push(...rest.split(/\s*,\s*/));
        rest = '';
      }
      if (rest) references.push(rest.replace(/\s+/g, ' '));
    }
    if (numbers.length === 0) return whole;
    const chips = [...new Set(numbers)].map(CHIP).join('');
    return references.length ? `${chips} *(${references.join('; ')})*` : chips;
  });
  // 3. Placeholders that were not inside an outer group
  return grouped.replace(MARKS, (_: string, n: string) => CHIP(n));
}

// A claim of the answer that its sources do not back after the claim check (issue #82). `text` is an exact
// substring of the answer without citation markers.
export interface ClaimFlag {
  text: string;
  verdict: 'unsupported' | 'uncited';
}

// Markdown answer whose [n] citations are chips opening the cited source (onOpen); used by the chat and the
// benchmark view. Each flag's text is marked in the answer (<mark>, titled "Not supported by the cited sources" or
// "No source cited" by its verdict); a flag whose text is not in the answer is listed below it instead, as
// "Unchecked claim: <text>" with the same title.
const FLAG_TITLES: Record<ClaimFlag['verdict'], string> = {
  unsupported: 'Not supported by the cited sources',
  uncited: 'No source cited',
};

// Each flag's text found in the body -> a link to #flag-<verdict>, rendered as a <mark>; the flags not found
function markFlags(body: string, flags: ClaimFlag[]): { marked: string; missing: ClaimFlag[] } {
  let marked = body;
  const missing: ClaimFlag[] = [];
  for (const flag of flags) {
    const text = flag.text.trim();
    const at = text && !/[[\]]/.test(text) ? marked.indexOf(text) : -1;
    if (at < 0) {
      missing.push(flag);
      continue;
    }
    marked = `${marked.slice(0, at)}[${text}](#flag-${flag.verdict})${marked.slice(at + text.length)}`;
  }
  return { marked, missing };
}

export default function CitedMarkdown({ body, citations, onOpen, flags = [] }: {
  body: string;
  citations: Citation[];
  onOpen: (citation: Citation) => void;
  flags?: ClaimFlag[];
}) {
  const { marked, missing } = markFlags(citations.length > 0 ? linkCitations(body) : body, flags);
  return (
    <>
    <ReactMarkdown
      components={{
        a: ({ href, children }) => {
          const cited = href?.startsWith('#cite-') ? Number(href.slice(6)) : null;
          if (cited !== null) {
            const citation = citations.find((item) => item.n === cited);
            return (
              <button
                type="button"
                onClick={() => citation && onOpen(citation)}
                disabled={!citation}
                title={citation?.label ?? 'Source details not available'}
                className="mx-px inline-flex min-w-[1.25rem] translate-y-[-1px] items-center justify-center rounded bg-blue-100 px-1 align-baseline text-[10px] font-semibold leading-4 text-blue-700 no-underline hover:bg-blue-200 disabled:cursor-default disabled:bg-zinc-100 disabled:text-zinc-500 dark:bg-blue-950 dark:text-blue-300 dark:hover:bg-blue-900"
              >
                {children}
              </button>
            );
          }
          if (href === '#flag-unsupported' || href === '#flag-uncited') {
            const title = FLAG_TITLES[href === '#flag-uncited' ? 'uncited' : 'unsupported'];
            return (
              <mark title={title} className="rounded bg-amber-100 px-0.5 text-inherit underline decoration-amber-500 decoration-wavy dark:bg-amber-900/40">
                {children}
              </mark>
            );
          }
          return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
        },
      }}
    >
      {marked}
    </ReactMarkdown>
    {missing.length > 0 && (
      <ul className="mt-2 space-y-1 text-xs text-amber-700 dark:text-amber-400">
        {missing.map((flag) => (
          <li key={flag.text} title={FLAG_TITLES[flag.verdict]}>Unchecked claim: {flag.text}</li>
        ))}
      </ul>
    )}
    </>
  );
}
