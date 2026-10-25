'use client';

import type { Pin } from '@/lib/place';

export interface PlacePanelProps {
  pin: Pin | null;
  onPinChange: (pin: Pin) => void;
  onClose: () => void;
}

/**
 * The map panel beside the conversation (labelled "Map"): a click on the map moves the pin, and the place card of
 * the pin is fetched and shown under the map, with the property, plans and zones outlined on it.
 */
export default function PlacePanel(props: PlacePanelProps) {
  void props;
  throw new Error('not implemented');
}
