'use client';

import { useEffect, useMemo, useState } from 'react';
import { Loader2, MapPin, X } from 'lucide-react';

import PlaceCard from '@/components/place/PlaceCard';
import PlaceMap, { type PlaceOutline } from '@/components/place/PlaceMap';
import { fetchPlaceCoverage, fetchPlaceProfile, type Pin, type PlaceProfile } from '@/lib/place';

export interface PlacePanelProps {
  pin: Pin | null;
  onPinChange: (pin: Pin) => void;
  onClose: () => void;
}

type Lookup = { pin: Pin; profile: PlaceProfile | null; error: string | null };

function outlinesOf(profile: PlaceProfile | null): PlaceOutline[] {
  if (!profile) return [];
  return [
    ...(profile.property ? [{ id: 'property', kind: 'property' as const, geometry: profile.property.geometry }] : []),
    ...profile.plans.map((plan, i) => ({ id: `plan-${i}`, kind: 'plan' as const, geometry: plan.geometry })),
    ...profile.zones.map((zone, i) => ({ id: `zone-${i}`, kind: 'zone' as const, geometry: zone.geometry })),
  ];
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
 * the pin is fetched and shown under the map, with the property, plans and zones outlined on it.
 */
export default function PlacePanel({ pin, onPinChange, onClose }: PlacePanelProps) {
  const [lookup, setLookup] = useState<Lookup | null>(null);
  const [bounds, setBounds] = useState<[number, number, number, number] | null>(null);

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

  return (
    <aside
      aria-label="Map"
      className="flex h-full w-[420px] shrink-0 flex-col border-l border-zinc-200 bg-zinc-50 motion-safe:animate-[slide-in-right_240ms_cubic-bezier(0.2,0.8,0.2,1)] dark:border-zinc-800 dark:bg-zinc-950"
    >
      <header className="flex items-center gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <MapPin size={16} className="text-zinc-500" aria-hidden />
        <h2 className="flex-1 text-sm font-semibold text-zinc-900 dark:text-zinc-100">Place</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close map"
          className="rounded-lg p-1.5 text-zinc-500 transition-transform duration-100 hover:bg-zinc-200 active:scale-95 dark:hover:bg-zinc-800"
        >
          <X size={16} />
        </button>
      </header>
      <div className="h-72 shrink-0 border-b border-zinc-200 dark:border-zinc-800">
        <PlaceMap pin={pin} outlines={outlines} bounds={bounds} onMapClick={onPinChange} />
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {!pin && <p className="text-sm text-zinc-500 dark:text-zinc-400">Click the map to pin a place in Uppsala.</p>}
        {pin && !settled && (
          <p role="status" className="mb-3 flex items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
            <Loader2 size={12} className="animate-spin" aria-hidden /> Looking up the place…
          </p>
        )}
        {shown?.error && settled && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">{`Could not look up this place: ${shown.error}`}</p>
        )}
        {shown?.profile && (
          <div className={settled ? '' : 'opacity-50 transition-opacity'}>
            <PlaceCard profile={shown.profile} />
          </div>
        )}
      </div>
    </aside>
  );
}
