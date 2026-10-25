'use client';

import type { PlaceSearchResult } from '@/lib/place';

export interface PlaceSearchProps {
  onPropose: (result: PlaceSearchResult) => void; // a match was chosen: propose a pin there
}

/**
 * The floating search field of the map panel (labelled "Search for a place"): pressing Enter searches Swedish
 * addresses and place names and lists the matches, pilot kommuner first; nothing is searched while typing. A search
 * with no match says so and suggests a street address or pinning by hand; a failed search says the service is
 * unavailable. The list credits OpenStreetMap / Nominatim.
 */
export default function PlaceSearch(props: PlaceSearchProps) {
  void props;
  throw new Error('not implemented');
}
