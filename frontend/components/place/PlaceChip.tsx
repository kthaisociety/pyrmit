'use client';

import { MapPin, X } from 'lucide-react';

import type { PinnedPlace } from '@/lib/place';

export interface PlaceChipProps {
  place: PinnedPlace;
  onOpen: () => void; // opens the map panel
  onClear: () => void; // removes the pin from the chat
}

/** The pinned place above the message input: its label (or the point), a tap opens the map, × clears the pin. */
export default function PlaceChip({ place, onOpen, onClear }: PlaceChipProps) {
  const label = place.label ?? `${place.lat.toFixed(5)}, ${place.lon.toFixed(5)}`;
  return (
    <div className="inline-flex max-w-full items-center rounded-full bg-white/80 pl-1 pr-1 text-[13px] shadow-[0_2px_12px_rgba(0,0,0,0.08)] ring-1 ring-black/5 backdrop-blur-xl [font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif] dark:bg-zinc-800/80 dark:ring-white/10">
      <button
        type="button"
        onClick={onOpen}
        className="flex min-w-0 items-center gap-1.5 rounded-full py-1 pl-1.5 pr-2 font-medium text-zinc-800 transition-transform duration-100 active:scale-[0.97] dark:text-zinc-100"
      >
        <span className="grid size-5 shrink-0 place-items-center rounded-full bg-[#ff375f] text-white" aria-hidden>
          <MapPin size={11} strokeWidth={2.75} />
        </span>
        <span className="truncate">{label}</span>
      </button>
      <button
        type="button"
        onClick={onClear}
        aria-label="Clear pin"
        className="grid size-6 shrink-0 place-items-center rounded-full text-zinc-500 transition-transform duration-100 hover:bg-zinc-200/70 active:scale-90 dark:hover:bg-zinc-700"
      >
        <X size={13} strokeWidth={2.5} />
      </button>
    </div>
  );
}
