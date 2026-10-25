'use client';

import { type FormEvent, useState } from 'react';
import { Loader2, MapPin, Search } from 'lucide-react';

import { searchPlaces, type PlaceSearchResult } from '@/lib/place';

export interface PlaceSearchProps {
  onPropose: (result: PlaceSearchResult) => void; // a match was chosen: propose a pin there
}

type SearchState =
  | { status: 'idle' }
  | { status: 'searching' }
  | { status: 'done'; query: string; results: PlaceSearchResult[] }
  | { status: 'failed'; message: string };

const GLASS = 'bg-white/80 backdrop-blur-2xl backdrop-saturate-150 ring-1 ring-black/5 shadow-[0_8px_32px_rgba(0,0,0,0.14)] dark:bg-zinc-900/75 dark:ring-white/10';

/**
 * The floating search field of the map panel (labelled "Search for a place"): pressing Enter searches Swedish
 * addresses and place names and lists the matches, pilot kommuner first; nothing is searched while typing. A search
 * with no match says so and suggests a street address or pinning by hand; a failed search says the service is
 * unavailable. The list credits OpenStreetMap / Nominatim.
 */
export default function PlaceSearch({ onPropose }: PlaceSearchProps) {
  const [query, setQuery] = useState('');
  const [state, setState] = useState<SearchState>({ status: 'idle' });

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const text = query.trim();
    if (text.length < 2 || state.status === 'searching') return; // one search at a time
    setState({ status: 'searching' });
    try {
      setState({ status: 'done', query: text, results: await searchPlaces(text) });
    } catch (err) {
      setState({ status: 'failed', message: (err as Error).message });
    }
  };

  const choose = (result: PlaceSearchResult) => {
    setState({ status: 'idle' });
    onPropose(result);
  };

  return (
    <div className="space-y-1.5">
      <form onSubmit={submit} role="search" className={`flex items-center gap-2 rounded-xl px-3 ${GLASS}`}>
        {state.status === 'searching'
          ? <Loader2 size={15} className="shrink-0 animate-spin text-zinc-500" aria-hidden />
          : <Search size={15} className="shrink-0 text-zinc-500" aria-hidden />}
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search address or place"
          aria-label="Search for a place"
          enterKeyHint="search"
          className="h-9 min-w-0 flex-1 bg-transparent text-[14px] text-zinc-900 placeholder:text-zinc-500 focus:outline-none dark:text-zinc-100"
        />
      </form>

      {state.status === 'failed' && (
        <p role="alert" className={`rounded-xl px-3 py-2 text-[13px] text-red-600 dark:text-red-400 ${GLASS}`}>
          {state.message}
        </p>
      )}

      {state.status === 'done' && (
        <div className={`overflow-hidden rounded-xl ${GLASS}`}>
          {state.results.length === 0 ? (
            <p className="px-3 py-2.5 text-[13px] text-zinc-600 dark:text-zinc-300">
              {`No match for "${state.query}". Try a street address with its town, or pin the place on the map.`}
            </p>
          ) : (
            <ul aria-label="Search results" className="max-h-64 divide-y divide-zinc-200/70 overflow-y-auto dark:divide-white/10">
              {state.results.map((result, i) => (
                <li key={`${result.lat},${result.lon},${i}`}>
                  <button
                    type="button"
                    onClick={() => choose(result)}
                    className="flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors hover:bg-black/5 active:bg-black/10 dark:hover:bg-white/5"
                  >
                    <span className={`mt-0.5 grid size-6 shrink-0 place-items-center rounded-full text-white ${result.in_pilot ? 'bg-[#ff375f]' : 'bg-zinc-400'}`} aria-hidden>
                      <MapPin size={12} strokeWidth={2.5} />
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-[13px] font-semibold text-zinc-900 dark:text-zinc-50">{result.label}</span>
                      <span className="block text-[11px] text-zinc-500 dark:text-zinc-400">
                        {[result.kommun, result.in_pilot ? null : 'not covered yet'].filter(Boolean).join(' · ')}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="border-t border-zinc-200/70 px-3 py-1 text-[10px] text-zinc-400 dark:border-white/10">
            Search by Nominatim · © OpenStreetMap contributors
          </p>
        </div>
      )}
    </div>
  );
}
