// Unit tests for components/PipelineTrace.tsx.
import { render, screen } from '@testing-library/react';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';

import PipelineTrace from '@/components/PipelineTrace';

import { kungsangen } from '../../mocks/place';

const PLACE_EVENT = {
  stage: 'place',
  data: { pin: { lat: 59.8505, lon: 17.641, label: 'Uppsala Kungsängen 7:8' }, profile: { property: null } },
};

describe('pipeline inspector', () => {
  it('shows the place an answer used in the pipeline inspector', () => {
    /** The inspector has a Place step naming the pinned property. */
    render(createElement(PipelineTrace, {
      events: [{ stage: 'place', data: { pin: PLACE_EVENT.data.pin, profile: kungsangen } }],
    }));

    expect(screen.getByText('Place')).toBeInTheDocument();
    expect(screen.getByText(/Uppsala Kungsängen 7:8/)).toBeInTheDocument();
  });
});
