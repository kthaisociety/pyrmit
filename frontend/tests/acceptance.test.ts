// Acceptance tests of #55 (see plan polygons for every registry kommun on the map): the review mode of the map panel
// and the review lookups, against the fake backend (PCR-0008). The base map is a stand-in: WebGL does not run in
// jsdom. Folded into the module test files by unit-test-ticket.
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createElement, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import type { PlaceMapProps } from '@/components/place/PlaceMap';
import PlacePanel, { REVIEW_PLANS_ZOOM } from '@/components/place/PlacePanel';
import { fetchPlansInView, fetchReviewCoverage, type BBox, type Pin } from '@/lib/place';

import { reviewCoverage, reviewPlans } from './mocks/place';
import { server } from './mocks/server';

const NACKA: BBox = [18.0, 59.25, 18.4, 59.4];

vi.mock('@/components/place/PlaceMap', () => ({
  default: (props: PlaceMapProps) =>
    createElement(
      'div',
      { 'data-testid': 'map',
        'data-review': props.review ? 'on' : 'off',
        'data-review-kommuner': props.review?.coverage ? String(props.review.coverage.features.length) : '',
        'data-review-plans': props.review?.plans ? String(props.review.plans.features.length) : '' },
      createElement('button', { onClick: () => props.onViewChange?.({ bbox: NACKA, zoom: REVIEW_PLANS_ZOOM + 2 }) },
                    'Zoom in on Nacka'),
      createElement('button', { onClick: () => props.onViewChange?.({ bbox: [10.5, 55, 24.5, 69.5], zoom: REVIEW_PLANS_ZOOM - 4 }) },
                    'Zoom out'),
    ),
}));

function Harness() {
  const [pin, setPin] = useState<Pin | null>(null);
  return createElement(PlacePanel, { pin, onPinChange: setPin, onClose: () => undefined });
}

function requestsTo(path: string): string[] {
  const seen: string[] = [];
  server.use(http.get(`*/api/place/review/${path}`, ({ request }) => {
    seen.push(new URL(request.url).search);
    return HttpResponse.json(path === 'coverage' ? reviewCoverage : reviewPlans);
  }));
  return seen;
}

const reviewToggle = () => screen.getByRole('button', { name: 'Review plan coverage' });

describe('review mode', () => {
  it('is off by default and the map is as before', () => {
    /** Before the user turns the review mode on, no coverage is fetched and the map gets no review layer. */
    const coverage = requestsTo('coverage');
    render(createElement(Harness));

    expect(reviewToggle()).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByTestId('map')).toHaveAttribute('data-review', 'off');
    expect(coverage).toEqual([]);
  });

  it('colours the kommuner by coverage once turned on', async () => {
    /** Turning the review mode on fetches every kommun's coverage and hands it to the map. */
    render(createElement(Harness));

    await userEvent.click(reviewToggle());

    expect(reviewToggle()).toHaveAttribute('aria-pressed', 'true');
    await waitFor(() => expect(screen.getByTestId('map')).toHaveAttribute('data-review-kommuner', '3'));
  });

  it('sums up the coverage in the panel', async () => {
    /** The panel says how many kommuner have polygons, so the reviewer need not count colours. */
    render(createElement(Harness));

    await userEvent.click(reviewToggle());

    expect(await screen.findByText(/2 of 3 kommuner with plan polygons/)).toBeInTheDocument();
  });

  it('fetches the plans in view once zoomed in to a kommun', async () => {
    /** Zoomed in past the threshold, the plans in the map's box are fetched for that box and drawn. */
    const plans = requestsTo('plans');
    render(createElement(Harness));
    await userEvent.click(reviewToggle());

    await userEvent.click(screen.getByRole('button', { name: 'Zoom in on Nacka' }));

    await waitFor(() => expect(screen.getByTestId('map')).toHaveAttribute('data-review-plans', '2'));
    expect(plans).toEqual([`?bbox=${encodeURIComponent(NACKA.join(','))}`]);
  });

  it('draws no plans zoomed out', async () => {
    /** Below the threshold the map shows the coverage colours only: no plans are fetched for the whole country. */
    const plans = requestsTo('plans');
    render(createElement(Harness));
    await userEvent.click(reviewToggle());
    await userEvent.click(screen.getByRole('button', { name: 'Zoom in on Nacka' }));
    await waitFor(() => expect(screen.getByTestId('map')).toHaveAttribute('data-review-plans', '2'));

    await userEvent.click(screen.getByRole('button', { name: 'Zoom out' }));

    await waitFor(() => expect(screen.getByTestId('map')).toHaveAttribute('data-review-plans', ''));
    expect(plans).toHaveLength(1);
  });

  it('asks the reviewer to zoom in when the view had more plans than served', async () => {
    /** A truncated answer is said in the panel, so a missing polygon is not read as a missing plan. */
    server.use(http.get('*/api/place/review/plans', () => HttpResponse.json({ ...reviewPlans, truncated: true })));
    render(createElement(Harness));
    await userEvent.click(reviewToggle());

    await userEvent.click(screen.getByRole('button', { name: 'Zoom in on Nacka' }));

    expect(await screen.findByText(/zoom in to see every plan/i)).toBeInTheDocument();
  });

  it('does not fetch plans while the review mode is off', async () => {
    /** Moving the map with the review mode off fetches nothing: the map behaves as it does today. */
    const plans = requestsTo('plans');
    render(createElement(Harness));
    expect(reviewToggle()).toHaveAttribute('aria-pressed', 'false');

    await userEvent.click(screen.getByRole('button', { name: 'Zoom in on Nacka' }));

    expect(plans).toEqual([]);
  });

  it('clears the review layers when turned off', async () => {
    /** Turning the review mode off takes the coverage and the plans off the map. */
    render(createElement(Harness));
    await userEvent.click(reviewToggle());
    await waitFor(() => expect(screen.getByTestId('map')).toHaveAttribute('data-review-kommuner', '3'));

    await userEvent.click(reviewToggle());

    expect(screen.getByTestId('map')).toHaveAttribute('data-review', 'off');
  });

  it('says when the coverage cannot be fetched', async () => {
    /** A failed coverage lookup is said in the panel instead of leaving the map uncoloured without a word. */
    server.use(http.get('*/api/place/review/coverage', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })));
    render(createElement(Harness));

    await userEvent.click(reviewToggle());

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not fetch the coverage/i);
  });
});

describe('review lookups', () => {
  it('fetches the coverage collection', async () => {
    /** The coverage lookup returns the backend's collection as is. */
    expect(await fetchReviewCoverage()).toEqual(reviewCoverage);
  });

  it('sends the box and returns the plans in it', async () => {
    /** The plans lookup asks for the box and returns the collection with its truncated flag. */
    const plans = requestsTo('plans');
    expect(await fetchPlansInView(NACKA)).toEqual(reviewPlans);
    expect(plans).toEqual([`?bbox=${encodeURIComponent('18,59.25,18.4,59.4')}`]);
  });

  it('throws the backend message when a box is refused', async () => {
    /** A refused box (422) surfaces as an Error carrying the backend's detail. */
    server.use(http.get('*/api/place/review/plans', () =>
      HttpResponse.json({ detail: 'The box is wider than a kommun.' }, { status: 422 })));
    await expect(fetchPlansInView([10.5, 55, 24.5, 69.5])).rejects.toThrow('The box is wider than a kommun.');
  });
});
