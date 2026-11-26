'use client';

import { useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import type { Citation } from '@/components/SourceViewer';
import { Flag } from 'lucide-react';
import { fill, useLanguage } from '@/lib/i18n';

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
// substring of the answer without citation markers; `unbacked` the sentences of it that lack backing, each an exact
// substring of `text` (absent or empty: the check did not say, the whole claim is flagged); `chunk_ids` the chunks
// the claim cites (none for an uncited claim).
export interface ClaimFlag {
  text: string;
  verdict: 'unsupported' | 'uncited';
  unbacked?: string[];
  chunk_ids?: string[];
}

// What a flag says on hover, by verdict (the page's dictionaries)
export const FLAG_HOVER = { unsupported: 'claim.unsupported', uncited: 'claim.uncited' } as const;

// The red flag after a flagged text (#138): its hover text is its name, a click opens the claim
function FlagButton({ label, onClick, onHover }: {
  label: string;
  onClick: () => void;
  onHover?: (hovered: boolean) => void;
}) {
  return (
    <button type="button" title={label} aria-label={label} onClick={onClick}
            onMouseEnter={() => onHover?.(true)} onMouseLeave={() => onHover?.(false)}
            onFocus={() => onHover?.(true)} onBlur={() => onHover?.(false)}
            className="ml-0.5 inline-flex translate-y-[1px] rounded p-0.5 align-baseline text-red-600 transition hover:bg-red-50 hover:text-red-700 dark:text-red-500 dark:hover:bg-red-950/60">
      <Flag size={12} fill="currentColor" aria-hidden />
    </button>
  );
}

// A text of the answer a flag is about: unmarked, tinted only while its flag is hovered or focused
function FlaggedText({ label, onOpen, children }: { label: string; onOpen: () => void; children: ReactNode }) {
  const [hovered, setHovered] = useState(false);
  return (
    <>
      <mark data-tinted={hovered}
            className={`rounded-sm text-inherit transition-colors ${hovered ? 'bg-red-100 dark:bg-red-950/70' : 'bg-transparent'}`}>
        {children}
      </mark>
      {'⁠' /* word joiner: the flag never wraps to a line of its own */}
      <FlagButton label={label} onClick={onOpen} onHover={setHovered} />
    </>
  );
}

// A flag's text becomes markdown link text, which cannot hold brackets
const canMark = (text: string) => text.length > 0 && !/[[\]]/.test(text);

// Each flag's texts found in the body -> links to #flag-<its index>, rendered as a FlaggedText: the sentences that
// lack backing when the check named them and the answer holds them, else the whole claim. `missing`: the flags
// with no text found in the body.
function markFlags(body: string, flags: ClaimFlag[]): { marked: string; missing: ClaimFlag[] } {
  let marked = body;
  const missing: ClaimFlag[] = [];
  const mark = (text: string, index: number): boolean => {
    const at = canMark(text) ? marked.indexOf(text) : -1;
    if (at < 0) return false;
    marked = `${marked.slice(0, at)}[${text}](#flag-${index})${marked.slice(at + text.length)}`;
    return true;
  };
  flags.forEach((flag, index) => {
    const sentences = (flag.unbacked ?? []).map((sentence) => sentence.trim());
    const found = sentences.filter((sentence) => mark(sentence, index)).length > 0 || mark(flag.text.trim(), index);
    if (!found) missing.push(flag);
  });
  return { marked, missing };
}

// Markdown answer whose [n] citations are chips opening the cited source (onOpen); used by the chat and the
// benchmark view. Each flag's text is left unmarked and followed by a red flag (#138) whose hover text says that
// the sources may not back the claim, or that it cites none, in the page language; hovering the flag tints the text
// it is about, a click hands the flag to onOpenFlag. A flag whose text is not in the answer is listed below it with
// its flag. When any claim is flagged, one line under the answer counts them.
export default function CitedMarkdown({ body, citations, onOpen, flags = [], onOpenFlag }: {
  body: string;
  citations: Citation[];
  onOpen: (citation: Citation) => void;
  flags?: ClaimFlag[];
  onOpenFlag?: (flag: ClaimFlag) => void;
}) {
  const { marked, missing } = markFlags(citations.length > 0 ? linkCitations(body) : body, flags);
  const { t } = useLanguage();
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
                title={citation?.label ?? t('source.detailsUnavailable')}
                className="mx-px inline-flex min-w-[1.25rem] translate-y-[-1px] items-center justify-center rounded bg-blue-100 px-1 align-baseline text-[10px] font-semibold leading-4 text-blue-700 no-underline hover:bg-blue-200 disabled:cursor-default disabled:bg-zinc-100 disabled:text-zinc-500 dark:bg-blue-950 dark:text-blue-300 dark:hover:bg-blue-900"
              >
                {children}
              </button>
            );
          }
          const flag = href?.startsWith('#flag-') ? flags[Number(href.slice(6))] : undefined;
          if (flag) {
            return (
              <FlaggedText label={t(FLAG_HOVER[flag.verdict])} onOpen={() => onOpenFlag?.(flag)}>
                {children}
              </FlaggedText>
            );
          }
          return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
        },
      }}
    >
      {marked}
    </ReactMarkdown>
    {missing.length > 0 && (
      <ul className="mt-2 list-none space-y-1 pl-0 text-xs text-zinc-600 dark:text-zinc-300">
        {missing.map((flag) => (
          <li key={flag.text} className="pl-0">
            <FlagButton label={t(FLAG_HOVER[flag.verdict])} onClick={() => onOpenFlag?.(flag)} />{' '}
            <span>{flag.text}</span>
          </li>
        ))}
      </ul>
    )}
    {flags.length > 0 && (
      <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
        {flags.length === 1 ? t('claim.countOne') : fill(t('claim.countMany'), { n: String(flags.length) })}
      </p>
    )}
    </>
  );
}
