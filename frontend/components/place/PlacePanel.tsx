'use client';

import { useEffect, useMemo, useState } from 'react';
import { Loader2, X } from 'lucide-react';

import PlaceCard from '@/components/place/PlaceCard';
import PlaceMap, { type PlaceOutline } from '@/components/place/PlaceMap';
import { fetchPlaceCoverage, fetchPlaceProfile, type Pin, type PlaceProfile } from '@/lib/place';

export interface PlacePanelProps {
  pin: Pin | null;
  onPinChange: (pin: Pin) => void;
  onClose: () => void;
}

type Lookup = { pin: Pin; profile: PlaceProfile | null; error: string | null };

// The system font (SF Pro on Apple devices), as in Apple Maps
const SYSTEM_FONT = '[font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif]';
// Floating glass: translucent, blurred, with a light top edge
const GLASS = 'bg-white/80 backdrop-blur-2xl backdrop-saturate-150 ring-1 ring-black/5 shadow-[0_8px_32px_rgba(0,0,0,0.14)] dark:bg-zinc-900/75 dark:ring-white/10';

function outlinesOf(profile: PlaceProfile | null): PlaceOutline[] {
  if (!profile) return [];
  return [
    ...(profile.property ? [{ id: 'property', kind: 'property' as const, geometry: profile.property.geometry }] : []),
    ...profile.plans.map((plan, i) => ({ id: `plan-${i}`, kind: 'plan' as const, geometry: plan.geometry })),
    ...profile.zones.map((zone, i) => ({ id: `zone-${i}`, kind: 'zone' as const, geometry: zone.geometry })),
  ];
}

// The share of the panel the card covers: expanded from 38 % of the height, collapsed or empty a strip
function sheetCover(hasCard: boolean, expanded: boolean): number {
  if (!hasCard) return 0.1;
  return expanded ? 0.6 : 0.16;
}

function union(boxes: [number, number, number, number][]): [number, number, number, number] | null {
  if (boxes.length === 0) return null;
  return [
    Math.min(...boxes.map((box) => box[0])), Math.min(...boxes.map((box) => box[1])),
    Math.max(...boxes.map((box) => box[2])), Math.max(...boxes.map((box) => box[3])),
  ];
}

/**
 * The map panel beside the conversation (labelled "Map"): a click on the map moves the pin, and the place card of
 * the pin is fetched and shown in a sheet over the map, with the property, plans and zones outlined on it.
 */
export default function PlacePanel({ pin, onPinChange, onClose }: PlacePanelProps) {
  const [lookup, setLookup] = useState<Lookup | null>(null);
  const [bounds, setBounds] = useState<[number, number, number, number] | null>(null);
  const [expanded, setExpanded] = useState(true);

  useEffect(() => {
    fetchPlaceCoverage()
      .then((kommuner) => setBounds(union(kommuner.map((kommun) => kommun.bbox))))
      .catch(() => setBounds(null)); // the map then opens on all of Sweden
  }, []);

  // A late answer for a pin the user has already moved is dropped
  useEffect(() => {
    if (!pin) return;
    let current = true;
    fetchPlaceProfile(pin)
      .then((profile) => current && setLookup({ pin, profile, error: null }))
      .catch((err: Error) => current && setLookup({ pin, profile: null, error: err.message }));
    return () => {
      current = false;
    };
  }, [pin]);

  const settled = lookup !== null && pin !== null && lookup.pin === pin;
  const shown = pin ? lookup : null; // keep the previous card, dimmed, while the next one loads
  const outlines = useMemo(() => outlinesOf(shown?.profile ?? null), [shown]);
  const hasCard = Boolean(pin);

  return (
    <aside
      aria-label="Map"
      className={`place-map relative h-full w-[440px] shrink-0 overflow-hidden border-l border-zinc-200 bg-zinc-100 ${SYSTEM_FONT} motion-safe:animate-[slide-in-right_280ms_cubic-bezier(0.32,0.72,0,1)] dark:border-zinc-800 dark:bg-zinc-900`}
    >
      <div className="absolute inset-0">
        <PlaceMap pin={pin} outlines={outlines} bounds={bounds} bottomInset={sheetCover(hasCard, expanded)}
                  onMapClick={onPinChange} />
      </div>

      <button
        type="button"
        onClick={onClose}
        aria-label="Close map"
        className={`absolute right-3 top-3 z-10 grid size-8 place-items-center rounded-full text-zinc-600 transition-transform duration-100 active:scale-90 dark:text-zinc-300 ${GLASS}`}
      >
        <X size={16} strokeWidth={2.5} />
      </button>

      <div
        className={`absolute inset-x-2 bottom-2 z-10 flex flex-col overflow-hidden rounded-[22px] transition-[top] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] motion-reduce:transition-none ${GLASS} ${
          hasCard ? (expanded ? 'top-[38%]' : 'top-[calc(100%-7.5rem)]') : 'top-[calc(100%-4.25rem)]'
        }`}
      >
        <button
          type="button"
          onClick={() => setExpanded((open) => !open)}
          disabled={!hasCard}
          aria-label={expanded ? 'Collapse place card' : 'Expand place card'}
          aria-expanded={expanded}
          className="flex shrink-0 justify-center pb-1 pt-2 disabled:cursor-default"
        >
          <span className="h-[5px] w-9 rounded-full bg-zinc-400/60 dark:bg-zinc-500/60" />
        </button>
        <div className="flex-1 overflow-y-auto overscroll-contain px-4 pb-4">
          {!pin && (
            <p className="py-1 text-[13px] text-zinc-500 dark:text-zinc-400">Click the map to pin a place in Uppsala.</p>
          )}
          {pin && !settled && (
            <p role="status" className="mb-3 flex items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
              <Loader2 size={12} className="animate-spin" aria-hidden /> Looking up the place…
            </p>
          )}
          {shown?.error && settled && (
            <p role="alert" className="text-[13px] text-red-600 dark:text-red-400">{`Could not look up this place: ${shown.error}`}</p>
          )}
          {shown?.profile && (
            <div className={settled ? '' : 'opacity-50 transition-opacity'}>
              <PlaceCard profile={shown.profile} />
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
