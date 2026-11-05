// Acceptance tests of #56: the place card's plan row lists the plan's documents from the corpus.
import { render, screen, within } from '@testing-library/react';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';

import PlaceCard from '@/components/place/PlaceCard';
import type { PlaceFeature, PlaceProfile } from '@/lib/place';

import { kungsangen } from './mocks/place';

const MAP = { doc_id: 'pdf:0380:map', role: 'plankarta', title: 'Plankarta (PDF, 3 MB)', url: 'https://www.uppsala.se/atle/plankarta.pdf' };
const DESCRIPTION = { doc_id: 'pdf:0380:text', role: 'planbeskrivning', title: 'Planbeskrivning (PDF)', url: 'https://www.uppsala.se/atle/beskrivning.pdf' };

function withPlans(...changes: Partial<PlaceFeature>[]): PlaceProfile {
  return { ...kungsangen, plans: changes.map((change, i) => ({ ...kungsangen.plans[i], ...change })) };
}

function planRows(profile: PlaceProfile) {
  render(createElement(PlaceCard, { profile }));
  return within(screen.getByRole('list', { name: 'Detaljplaner' })).getAllByRole('listitem');
}

describe('plan documents on the place card', () => {
  it('lists a plan map with its role and a link', () => {
    /** A plan with documents links each by its role: the plan map. */
    const [row] = planRows(withPlans({ text_status: 'read', corpus_documents: [MAP, DESCRIPTION] }));
    expect(within(row).getByRole('link', { name: /plan map/i })).toHaveAttribute('href', MAP.url);
  });

  it('lists a plan description with its role and a link', () => {
    /** A plan with documents links each by its role: the plan description. */
    const [row] = planRows(withPlans({ text_status: 'read', corpus_documents: [MAP, DESCRIPTION] }));
    expect(within(row).getByRole('link', { name: /plan description/i })).toHaveAttribute('href', DESCRIPTION.url);
  });

  it('says a plan without documents has no text read', () => {
    /** A plan with no document says so and does not claim to have text. */
    const [row] = planRows(withPlans({ text_status: 'none', corpus_documents: [] }));
    expect(within(row).getByText(/no text read/i)).toBeInTheDocument();
  });

  it('keeps the link to the kommun on a plan without documents', () => {
    /** A plan with no document keeps its link to the kommun. */
    const plan = kungsangen.plans[0];
    const [row] = planRows(withPlans({ text_status: 'none', corpus_documents: [], documents: [], url: plan.url }));
    expect(within(row).getByRole('link', { name: /documents/i })).toHaveAttribute('href', plan.url);
  });

  it('gives each of several plans its own documents', () => {
    /** A point covered by several plans lists each with its own documents. */
    const rows = planRows(withPlans(
      { text_status: 'read', corpus_documents: [MAP] },
      { text_status: 'read', corpus_documents: [DESCRIPTION] },
    ));
    expect(within(rows[0]).getByRole('link', { name: /plan map/i })).toBeInTheDocument();
    expect(within(rows[0]).queryByRole('link', { name: /plan description/i })).toBeNull();
    expect(within(rows[1]).getByRole('link', { name: /plan description/i })).toBeInTheDocument();
  });

  it('says the documents could not be read when the corpus is down, not that there is no text', () => {
    /** The corpus being unreachable keeps the row and tells it apart from a plan without text. */
    const [row] = planRows(withPlans({ text_status: 'unavailable', corpus_documents: [] }));
    expect(within(row).getByText(/documents could not be read/i)).toBeInTheDocument();
    expect(within(row).queryByText(/no text read/i)).toBeNull();
  });
});
