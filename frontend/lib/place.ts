// Place lookups for the chat's map pin: the place profile of a point and the kommuner the map covers
// (backend/place/, GET /api/place/*).

export interface Pin {
  lat: number;
  lon: number;
}

// One row of the place card: a plan, a land-use zone or a plan in progress, from a named source
export interface PlaceFeature {
  layer: string;
  kind: string; // plan | plan_addition | area_regulations | plan_pending | zone | ...
  layer_title: string;
  name: string | null;
  ref: string | null; // aktbeteckning, zone code, ...
  type: string | null;
  date: string | null; // laga kraft date (ISO)
  status: string | null;
  authority: string | null;
  law: string | null;
  text: string | null;
  url: string | null;
  note: string | null;
  source: string;
  fetched: string;
  geometry: GeoJSON.Geometry;
  share?: number; // zones: fraction of the property covered
  corpus_plan_id?: string | null;
  provisions_indexed?: boolean;
}

export interface PlaceLayer {
  id: string;
  title: string;
  provider: string;
  licence: string;
  fetched: string | null;
  status: 'ok' | 'unavailable';
}

export interface PlaceProfile {
  point: Pin;
  kommun: { code: string; name: string } | null;
  covered: boolean;
  property: { designation: string; geometry: GeoJSON.Geometry; source: string; fetched: string } | null;
  property_status: 'found' | 'none' | 'unavailable' | 'not_covered';
  detaljplan: 'inside' | 'outside' | 'unknown';
  plans: PlaceFeature[];
  zones: PlaceFeature[];
  pending_plans: PlaceFeature[];
  layers: PlaceLayer[];
  notes: string[];
}

export interface PlaceCoverage {
  code: string;
  name: string;
  bbox: [number, number, number, number]; // west, south, east, north
  fetched: string;
}

/** The place profile of a pinned point. Throws an Error with the backend's message when the lookup fails. */
export async function fetchPlaceProfile(pin: Pin): Promise<PlaceProfile> {
  void pin;
  throw new Error('not implemented');
}

/** The pilot kommuner the map covers, for its first view. Throws an Error when the lookup fails. */
export async function fetchPlaceCoverage(): Promise<PlaceCoverage[]> {
  throw new Error('not implemented');
}
