import { http, HttpResponse } from 'msw';

import { kaboOutside, kungsangen } from './place';

// Default fake backend shared by every test. Override per test with server.use(...).
export const handlers = [
  // The place profile: Kungsängen 7:8 near the centre of Uppsala, Kåbo 1:1 (outside any plan) further north
  http.get('*/api/place/profile', ({ request }) => {
    const lat = Number(new URL(request.url).searchParams.get('lat'));
    return HttpResponse.json(lat > 59.87 ? kaboOutside : kungsangen);
  }),
  http.get('*/api/place/coverage', () =>
    HttpResponse.json([{ code: '0380', name: 'Uppsala', bbox: [17.5, 59.7, 17.9, 60.0], fetched: '2026-10-25' }]),
  ),
  http.get('*/api/sessions', () =>
    HttpResponse.json([
      { id: 's1', title: 'Bygglov Storgatan 3', created_at: '2026-10-01T10:00:00Z' },
      { id: 's2', title: null, created_at: '2026-10-02T10:00:00Z' },
    ]),
  ),
  http.delete('*/api/sessions/:sessionId', () => new HttpResponse(null, { status: 204 })),
];
