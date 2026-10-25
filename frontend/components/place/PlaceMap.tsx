'use client';

import type { Pin } from '@/lib/place';

export interface PlaceOutline {
  id: string;
  kind: 'property' | 'plan' | 'zone';
  geometry: GeoJSON.Geometry;
}

export interface PlaceMapProps {
  pin: Pin | null;
  outlines: PlaceOutline[]; // drawn over the base map: the property, its plans and zones
  bounds?: [number, number, number, number] | null; // west, south, east, north: first view
  onMapClick: (pin: Pin) => void;
}

/** The base map (MapLibre, OpenFreeMap tiles) with the pin and the outlines; a click reports the point. */
export default function PlaceMap(props: PlaceMapProps) {
  void props;
  throw new Error('not implemented');
}
