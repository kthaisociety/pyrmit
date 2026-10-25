// Unit tests for lib/place.ts.
import { describe, expect, it } from 'vitest';

import { placeFromHistory, placeLabel } from '@/lib/place';

import { kungsangen, street } from '../../mocks/place';

const PLACE_EVENT = {
  stage: 'place',
  data: { pin: { lat: 59.8505, lon: 17.641, label: 'Uppsala Kungsängen 7:8' }, profile: { property: null } },
};

describe('place labels', () => {
  it('labels a place by its property', () => {
    /** The chip label is the property's designation. */
    expect(placeLabel(kungsangen)).toBe('Uppsala Kungsängen 7:8');
  });

  it('labels a place without property by its point', () => {
    /** Without a property the label is the point. */
    expect(placeLabel(street)).toBe('59.85050, 17.64100');
  });

  it('takes the latest place of a history', () => {
    /** The latest answer with a place wins; answers without one are skipped. */
    const older = { stage: 'place', data: { pin: { lat: 1, lon: 2, label: 'Old' }, profile: {} } };
    expect(placeFromHistory([[older], null, [PLACE_EVENT], [{ stage: 'call', data: {} }]])).toEqual(
      { lat: 59.8505, lon: 17.641, label: 'Uppsala Kungsängen 7:8' });
    expect(placeFromHistory([null, []])).toBeNull();
  });
});
