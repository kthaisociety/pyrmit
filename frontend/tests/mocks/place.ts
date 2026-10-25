// Place profiles the fake backend serves (GET /api/place/profile), shaped like backend/place/profile.py.
import type { PlaceFeature, PlaceProfile } from '@/lib/place';

const square = (west: number, south: number, east: number, north: number): GeoJSON.Polygon => ({
  type: 'Polygon',
  coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
});

const row = (fields: Partial<PlaceFeature>): PlaceFeature => ({
  layer: 'plans', kind: 'plan', layer_title: 'Gällande detaljplaner', name: null, ref: null, type: null,
  date: null, status: null, authority: null, law: null, text: null, url: null, note: null,
  source: 'Uppsala kommun', fetched: '2026-10-25', geometry: square(17.64, 59.85, 17.642, 59.851), ...fields,
});

export const kungsangen: PlaceProfile = {
  point: { lat: 59.8505, lon: 17.641 },
  kommun: { code: '0380', name: 'Uppsala' },
  covered: true,
  property: { designation: 'Uppsala Kungsängen 7:8', geometry: square(17.64, 59.85, 17.642, 59.851),
              source: 'Uppsala kommun', fetched: '2026-10-25' },
  property_status: 'found',
  detaljplan: 'inside',
  plans: [
    row({ ref: '0380-P2012/9', kind: 'plan_addition', layer: 'plan_additions', layer_title: 'Tillägg till detaljplan',
          name: 'Tillägg till stadsplan för Kungsängen', date: '2012-06-01',
          url: 'https://www.uppsala.se/detaljplan/?aktbeteckning=0380-P2012/9', provisions_indexed: false }),
    row({ ref: '0380-O2005/1', kind: 'area_regulations', layer: 'area_regulations', layer_title: 'Områdesbestämmelser',
          name: 'Områdesbestämmelser Kungsängen', date: '2005-01-01',
          url: 'https://www.uppsala.se/detaljplan/?aktbeteckning=0380-O2005/1', provisions_indexed: false }),
    row({ ref: '0380-P2002/5', name: 'Del av Atle, Kungsängen 7:8', date: '2002-01-09',
          url: 'https://www.uppsala.se/detaljplan/?aktbeteckning=0380-P2002/5', corpus_plan_id: 'f41489',
          provisions_indexed: true, note: 'Tolkad, kan finnas osäkra gränser' }),
    row({ ref: '0380-P1990/3', name: 'Stadsplan för Kungsängen', date: '1990-03-12',
          url: 'https://www.uppsala.se/detaljplan/?aktbeteckning=0380-P1990/3', corpus_plan_id: null,
          provisions_indexed: false }),
  ],
  zones: [
    row({ ref: 'BCK', kind: 'zone', layer: 'zones_kvartersmark', layer_title: 'Kvartersmark (användning)',
          name: 'Bostäder, Centrumfunktion, Kontor', type: 'Kvarter', share: 0.75,
          note: 'Tolkad, kan finnas osäkra gränser' }),
    row({ ref: 'P', kind: 'zone', layer: 'zones_kvartersmark', layer_title: 'Kvartersmark (användning)',
          name: 'Parkering', type: 'Kvarter', share: 0.25, note: 'Tolkad, kan finnas osäkra gränser' }),
  ],
  pending_plans: [
    row({ kind: 'plan_pending', layer: 'plans_pending', layer_title: 'Pågående detaljplaner',
          name: 'Kungsängen 7:8 m.fl.', ref: 'PLA 2024-001', status: 'Samråd', text: 'Bostäder' }),
  ],
  protected_areas: [
    row({ kind: 'protected', layer: 'protected_areas', layer_title: 'Skyddade områden', name: 'Kungsängsängen',
          ref: '2001234', type: 'Naturreservat', authority: 'Länsstyrelsen', date: '1951-03-02',
          url: 'https://skyddadnatur.naturvardsverket.se/sknat/?nvrid=2001234', source: 'Naturvårdsverket' }),
  ],
  natura2000: [
    row({ kind: 'natura2000', layer: 'natura2000', layer_title: 'Natura 2000', name: 'Kungsängen', ref: 'SE0210071',
          type: 'SCI', url: 'https://natura2000.eea.europa.eu/Natura2000/SDF.aspx?site=SE0210071',
          source: 'Naturvårdsverket' }),
  ],
  national_interests: [
    row({ kind: 'national_interest', layer: 'riks_kulturmiljo', layer_title: 'Riksintresse kulturmiljövård',
          name: 'Uppsala stad', type: 'Riksintresse kulturmiljövård', law: 'MB 3 kap. 6 §',
          url: 'https://www.raa.se/riksintressen/c40', source: 'Boverket (sammanställning)' }),
  ],
  ancient_remains: [
    row({ kind: 'ancient_remain', layer: 'raa_lamningar', layer_title: 'Lämningar', name: 'Gravfält',
          ref: 'Uppsala 123:1', type: 'Gravfält', status: 'Fornlämning',
          url: 'https://pub.raa.se/visa/objekt/lamning/d4e16ab8', source: 'Riksantikvarieämbetet' }),
  ],
  strandskydd: {
    status: 'not_checked',
    reason: 'The länsstyrelser\'s strandskydd services could not be reached.',
    note: 'A strandskyddsdispens may be needed within 100 m of a shoreline.',
  },
  permits: [
    { title: 'Bygglov (building permit)', law: 'PBL 9 kap.', authority: 'Byggnadsnämnden, Uppsala kommun',
      reason: 'Tested against the detaljplan.', kind: 'permit' },
    { title: 'Dispens from the naturreservat regulations of Kungsängsängen', law: 'MB 7 kap. 7 §',
      authority: 'Länsstyrelsen', reason: 'The property lies in a naturreservat.', kind: 'permit' },
    { title: 'Uppsala stad: the prövning must not significantly harm this riksintresse', law: 'MB 3 kap. 6 §',
      authority: 'Uppsala kommun / Länsstyrelsen', reason: 'Riksintresse kulturmiljövård.', kind: 'consideration' },
  ],
  section_status: { protected_areas: 'ok', natura2000: 'ok', national_interests: 'ok', ancient_remains: 'ok' },
  layers: [
    { id: 'plans', title: 'Gällande detaljplaner', provider: 'Uppsala kommun', licence: 'open data',
      fetched: '2026-10-25', status: 'ok' },
  ],
  notes: ['Registry data, not a decision: the adopted plan documents and the authorities\' decisions are binding.'],
};

export const nothingAround: PlaceProfile = {
  ...kungsangen, protected_areas: [], natura2000: [], national_interests: [], ancient_remains: [],
  section_status: { protected_areas: 'ok', natura2000: 'unavailable', national_interests: 'ok', ancient_remains: 'ok' },
};

export const kaboOutside: PlaceProfile = {
  ...kungsangen,
  protected_areas: [], natura2000: [], national_interests: [], ancient_remains: [],
  point: { lat: 59.88, lon: 17.68 },
  property: { designation: 'Uppsala Kåbo 1:1', geometry: square(17.679, 59.879, 17.681, 59.881),
              source: 'Uppsala kommun', fetched: '2026-10-25' },
  detaljplan: 'outside',
  plans: [],
  zones: [],
  pending_plans: [],
};

export const street: PlaceProfile = { ...kungsangen, property: null, property_status: 'none', zones: [] };

export const notCovered: PlaceProfile = {
  ...kungsangen, point: { lat: 57.7, lon: 11.97 }, kommun: null, covered: false, property: null,
  property_status: 'not_covered', detaljplan: 'unknown', plans: [], zones: [], pending_plans: [], layers: [],
  protected_areas: [], natura2000: [], national_interests: [], ancient_remains: [], permits: [],
  section_status: { protected_areas: 'not_covered', natura2000: 'not_covered', national_interests: 'not_covered',
                    ancient_remains: 'not_covered' },
};

export const propertyUnavailable: PlaceProfile = { ...kungsangen, property: null, property_status: 'unavailable' };
