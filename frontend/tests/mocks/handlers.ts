import { http, HttpResponse } from 'msw';

// Default fake backend shared by every test. Override per test with server.use(...).
export const handlers = [
  http.get('*/api/sessions', () =>
    HttpResponse.json([
      { id: 's1', title: 'Bygglov Storgatan 3', created_at: '2026-10-01T10:00:00Z' },
      { id: 's2', title: null, created_at: '2026-10-02T10:00:00Z' },
    ]),
  ),
  http.delete('*/api/sessions/:sessionId', () => new HttpResponse(null, { status: 204 })),
];
