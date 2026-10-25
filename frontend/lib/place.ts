// Place lookups for the chat's map pin: the place profile of a point and the kommuner the map covers
// (backend/place/, GET /api/place/*).
import { authFetch } from '@/lib/auth';

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

// A permit or prövning the place points to, by fixed rules; a consideration is not a permit (e.g. a riksintresse)
export interface PlacePermit {
  title: string;
  law: string;
  authority: string;
  reason: string;
  kind: 'permit' | 'consideration';
}

export type SectionStatus = 'ok' | 'unavailable' | 'not_covered';

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
  protected_areas: PlaceFeature[];
  natura2000: PlaceFeature[];
  national_interests: PlaceFeature[];
  ancient_remains: PlaceFeature[];
  strandskydd: { status: 'not_checked'; reason: string; note: string };
  permits: PlacePermit[];
  // "ok": the sources answered (an empty list means none found); "unavailable": one did not
  section_status: Record<'protected_areas' | 'natura2000' | 'national_interests' | 'ancient_remains', SectionStatus>;
  layers: PlaceLayer[];
  notes: string[];
}

export interface PlaceCoverage {
  code: string;
  name: string;
  bbox: [number, number, number, number]; // west, south, east, north
  fetched: string;
}

async function getJson<T>(url: string): Promise<T> {
  const response = await authFetch(url);
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(typeof data?.detail === 'string' ? data.detail : `HTTP ${response.status}`);
  }
  return response.json();
}

/** The place profile of a pinned point. Throws an Error with the backend's message when the lookup fails. */
export async function fetchPlaceProfile(pin: Pin): Promise<PlaceProfile> {
  const query = new URLSearchParams({ lat: String(pin.lat), lon: String(pin.lon) });
  return getJson<PlaceProfile>(`/api/place/profile?${query}`);
}

/** The pilot kommuner the map covers, for its first view. Throws an Error when the lookup fails. */
export async function fetchPlaceCoverage(): Promise<PlaceCoverage[]> {
  return getJson<PlaceCoverage[]>('/api/place/coverage');
}

// The place a chat is about: the pin and the label its chip shows (sent with each question, ADR-0004)
export interface PinnedPlace extends Pin {
  label: string | null;
}

/** The chip's label for a place profile: the property and kommun ("Uppsala Kungsängen 7:8"), else the point. */
export function placeLabel(profile: PlaceProfile): string {
  if (profile.property) return profile.property.designation;
  return `${profile.point.lat.toFixed(5)}, ${profile.point.lon.toFixed(5)}`;
}

/**
 * The place a chat's history was last asked about: the pin of the latest "place" pipeline event of its answers'
 * traces (oldest message first), or null when no answer had one.
 */
export function placeFromHistory(traces: ({ stage: string; data: Record<string, unknown> }[] | null | undefined)[]): PinnedPlace | null {
  let latest: PinnedPlace | null = null;
  for (const event of traces.flatMap((trace) => trace ?? [])) {
    const pin = event.stage === 'place' ? (event.data.pin as Partial<PinnedPlace> | undefined) : undefined;
    if (typeof pin?.lat === 'number' && typeof pin?.lon === 'number') {
      latest = { lat: pin.lat, lon: pin.lon, label: pin.label ?? null };
    }
  }
  return latest;
}

// A match of the map's address search (Nominatim, Sweden only, pilot kommuner first)
export interface PlaceSearchResult {
  label: string; // e.g. "Kungsgatan 47A, Uppsala"
  lat: number;
  lon: number;
  kind: string | null;
  kommun: string | null;
  in_pilot: boolean;
}

/** Swedish addresses and place names matching the query. Throws an Error with the backend's message on failure. */
export async function searchPlaces(query: string): Promise<PlaceSearchResult[]> {
  void query;
  throw new Error('not implemented');
}
