// Acceptance tests of #52 (place lookup covers every kommun with an open plan layer), folded into the module
// test files by unit-test-ticket.
import { render, screen, within } from '@testing-library/react';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';

import PlaceCard from '@/components/place/PlaceCard';
import type { PlaceProfile } from '@/lib/place';

import { kungsangen } from './mocks/place';

const DOCUMENTS = ['https://infobank.nacka.se/ext/planer/93_62.pdf', 'https://infobank.nacka.se/ext/planer/Planbeskrivning%2093_62.pdf'];

function nacka(fields: Partial<PlaceProfile['plans'][number]>): PlaceProfile {
  const plan = { ...kungsangen.plans[2], ref: '0182-P93/62', name: 'Sicklaön 13:3', source: 'Nacka kommun',
                 url: DOCUMENTS[0], page: null, documents: DOCUMENTS, licence: 'unknown', ...fields };
  return { ...kungsangen, kommun: { code: '0182', name: 'Nacka' }, property: null, property_status: 'not_covered',
           plans: [plan], zones: [], pending_plans: [] };
}

describe('plan rows of a kommun with an open plan layer', () => {
  it('lists each document link of a plan by its file name', () => {
    /** A plan with document links shows one link per document, named by the file, instead of "Plan documents". */
    render(createElement(PlaceCard, { profile: nacka({}) }));
    const [row] = within(screen.getByRole('list', { name: 'Detaljplaner' })).getAllByRole('listitem');
    expect(within(row).getByRole('link', { name: '93_62.pdf' })).toHaveAttribute('href', DOCUMENTS[0]);
    expect(within(row).getByRole('link', { name: 'Planbeskrivning 93_62.pdf' })).toHaveAttribute('href', DOCUMENTS[1]);
    expect(within(row).queryByRole('link', { name: /plan documents/i })).toBeNull();
  });

  it('links the plan page beside its documents', () => {
    /** A plan that has a page as well as documents links the page as "Plan page". */
    const page = 'https://www.nacka.se/planer/sicklaon-13-3/';
    render(createElement(PlaceCard, { profile: nacka({ page, url: page }) }));
    const [row] = within(screen.getByRole('list', { name: 'Detaljplaner' })).getAllByRole('listitem');
    expect(within(row).getByRole('link', { name: 'Plan page' })).toHaveAttribute('href', page);
    expect(within(row).getByRole('link', { name: '93_62.pdf' })).toBeInTheDocument();
  });
});
