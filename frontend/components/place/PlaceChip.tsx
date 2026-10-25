'use client';

import type { PinnedPlace } from '@/lib/place';

export interface PlaceChipProps {
  place: PinnedPlace;
  onOpen: () => void; // opens the map panel
  onClear: () => void; // removes the pin from the chat
}

/** The pinned place above the message input: its label (or the point), a tap opens the map, × clears the pin. */
export default function PlaceChip(props: PlaceChipProps) {
  void props;
  throw new Error('not implemented');
}
