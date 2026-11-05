// Unit tests for lib/place.ts.
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import { fetchPlansInView, fetchReviewCoverage, placeFromHistory, placeLabel, type BBox } from '@/lib/place';

import { kungsangen, reviewCoverage, reviewPlans, street } from '../../mocks/place';
import { server } from '../../mocks/server';

const NACKA: BBox = [18.0, 59.25, 18.4, 59.4];

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

describe('review lookups', () => {
  it('fetches the coverage collection', async () => {
    /** The coverage lookup returns the backend's collection as is. */
    expect(await fetchReviewCoverage()).toEqual(reviewCoverage);
  });

  it('sends the box and returns the plans in it', async () => {
    /** The plans lookup asks for the box and returns the collection with its truncated flag. */
    const asked: string[] = [];
    server.use(http.get('*/api/place/review/plans', ({ request }) => {
      asked.push(new URL(request.url).search);
      return HttpResponse.json(reviewPlans);
    }));
    expect(await fetchPlansInView(NACKA)).toEqual(reviewPlans);
    expect(asked).toEqual([`?bbox=${encodeURIComponent('18,59.25,18.4,59.4')}`]);
  });

  it('throws the backend message when a box is refused', async () => {
    /** A refused box (422) surfaces as an Error carrying the backend's detail. */
    server.use(http.get('*/api/place/review/plans', () =>
      HttpResponse.json({ detail: 'The box is wider than a kommun.' }, { status: 422 })));
    await expect(fetchPlansInView([10.5, 55, 24.5, 69.5])).rejects.toThrow('The box is wider than a kommun.');
  });
});
