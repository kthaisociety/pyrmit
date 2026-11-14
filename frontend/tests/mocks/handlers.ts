import { http, HttpResponse } from 'msw';

import { kaboOutside, kungsangen, reviewCoverage, reviewPlans } from './place';

// Default fake backend shared by every test. Override per test with server.use(...).
export const handlers = [
  // The place profile: Kungsängen 7:8 near the centre of Uppsala, Kåbo 1:1 (outside any plan) further north
  http.get('*/api/place/profile', ({ request }) => {
    const lat = Number(new URL(request.url).searchParams.get('lat'));
    return HttpResponse.json(lat > 59.87 ? kaboOutside : kungsangen);
  }),
  http.get('*/api/place/search', () => HttpResponse.json([])),
  // The shared glossary of Swedish domain terms (backend/src/glossary.py), two of its entries
  http.get('*/api/glossary', () =>
    HttpResponse.json({ bygglov: 'building permit', detaljplan: 'detailed development plan' }),
  ),
  http.get('*/api/place/coverage', () =>
    HttpResponse.json([{ code: '0380', name: 'Uppsala', bbox: [17.5, 59.7, 17.9, 60.0], fetched: '2026-10-25' }]),
  ),
  http.get('*/api/place/review/coverage', () => HttpResponse.json(reviewCoverage)),
  http.get('*/api/place/review/plans', () => HttpResponse.json(reviewPlans)),
  http.get('*/api/sessions', () =>
    HttpResponse.json([
      { id: 's1', title: 'Bygglov Storgatan 3', created_at: '2026-10-01T10:00:00Z' },
      { id: 's2', title: null, created_at: '2026-10-02T10:00:00Z' },
    ]),
  ),
  http.delete('*/api/sessions/:sessionId', () => new HttpResponse(null, { status: 204 })),
  // The user's own OpenRouter key (issue #108): none set, the feature on
  http.get('*/api/auth/api-key', () => HttpResponse.json({ enabled: true, has_key: false, last4: null })),
];
