// Acceptance tests for #36: protected areas, national interests, ancient remains and likely permits on the place
// card. Temporary, folded into tests/unit/ by refactor-issue (PCR-0007).
import { render, screen, within } from '@testing-library/react';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';

import PlaceCard from '@/components/place/PlaceCard';

import { kungsangen, nothingAround } from './mocks/place';

function card(profile = kungsangen) {
  render(createElement(PlaceCard, { profile }));
}

function rows(name: string) {
  return within(screen.getByRole('list', { name })).getAllByRole('listitem');
}

describe('place card constraints', () => {
  it('lists the protected areas with type, name, authority, date and a link to the decision', () => {
    /** Each protected area shows its type, name, deciding authority, decision date and decision link. */
    card();
    const [reservat] = rows('Protected areas');
    expect(reservat).toHaveTextContent('Naturreservat');
    expect(reservat).toHaveTextContent('Kungsängsängen');
    expect(reservat).toHaveTextContent('Länsstyrelsen');
    expect(reservat).toHaveTextContent('1951-03-02');
    expect(within(reservat).getByRole('link', { name: /decision/i })).toHaveAttribute(
      'href', 'https://skyddadnatur.naturvardsverket.se/sknat/?nvrid=2001234');
  });

  it('lists Natura 2000 sites with their code and a link to the site', () => {
    /** Each Natura 2000 site shows its site code and links to its description. */
    card();
    const [site] = rows('Natura 2000');
    expect(site).toHaveTextContent('SE0210071');
    expect(within(site).getByRole('link', { name: /site/i })).toHaveAttribute(
      'href', 'https://natura2000.eea.europa.eu/Natura2000/SDF.aspx?site=SE0210071');
  });

  it('lists national interests with their kind, name, legal basis and a link', () => {
    /** Each national interest shows its kind, name, legal basis and description link. */
    card();
    const [interest] = rows('National interests');
    expect(interest).toHaveTextContent('Riksintresse kulturmiljövård');
    expect(interest).toHaveTextContent('Uppsala stad');
    expect(interest).toHaveTextContent('MB 3 kap. 6 §');
    expect(within(interest).getByRole('link', { name: /description/i })).toHaveAttribute(
      'href', 'https://www.raa.se/riksintressen/c40');
  });

  it('lists ancient remains with RAÄ number, type, antikvarisk bedömning and a Fornsök link', () => {
    /** Each remain shows its RAÄ number, type, assessment and links to Fornsök. */
    card();
    const [remain] = rows('Ancient remains');
    expect(remain).toHaveTextContent('Uppsala 123:1');
    expect(remain).toHaveTextContent('Gravfält');
    expect(remain).toHaveTextContent('Fornlämning');
    expect(within(remain).getByRole('link', { name: /fornsök/i })).toHaveAttribute(
      'href', 'https://pub.raa.se/visa/objekt/lamning/d4e16ab8');
  });

  it('shows strandskydd as not checked, with the reason and the 100 m reminder', () => {
    /** Strandskydd says it was not checked, why, and that a dispens may be needed within 100 m of a shoreline. */
    card();
    const strandskydd = screen.getByRole('region', { name: 'Strandskydd' });
    expect(strandskydd).toHaveTextContent(/not checked/i);
    expect(strandskydd).toHaveTextContent('could not be reached');
    expect(strandskydd).toHaveTextContent('100 m');
  });

  it('lists the likely permits with their legal basis and deciding authority', () => {
    /** Each likely permit shows its legal basis and the authority that decides it. */
    card();
    const [bygglov, dispens] = rows('Likely permits');
    expect(bygglov).toHaveTextContent('Bygglov');
    expect(bygglov).toHaveTextContent('PBL 9 kap.');
    expect(bygglov).toHaveTextContent('Byggnadsnämnden, Uppsala kommun');
    expect(dispens).toHaveTextContent('MB 7 kap. 7 §');
  });

  it('shows a national interest as a consideration, not a permit', () => {
    /** A consideration is labelled as such in the permit list. */
    card();
    const consideration = rows('Likely permits')[2];
    expect(consideration).toHaveTextContent(/consideration/i);
    expect(consideration).toHaveTextContent('must not significantly harm');
  });

  it('says none found when a section answered with nothing', () => {
    /** An empty, answered section says none was found. */
    card(nothingAround);
    expect(within(screen.getByRole('region', { name: 'Protected areas' })).getByText(/none found/i)).toBeInTheDocument();
  });

  it('says the source could not be reached when a section is unavailable', () => {
    /** An unanswered section says so instead of none found. */
    card(nothingAround);
    const natura = screen.getByRole('region', { name: 'Natura 2000' });
    expect(within(natura).getByText(/could not be reached/i)).toBeInTheDocument();
    expect(within(natura).queryByText(/none found/i)).not.toBeInTheDocument();
  });

  it('names the source and date of every new row', () => {
    /** Protected areas, Natura 2000 sites, national interests and remains each show source and date. */
    card();
    expect(rows('Protected areas')[0]).toHaveTextContent('Naturvårdsverket · 2026-10-25');
    expect(rows('Natura 2000')[0]).toHaveTextContent('Naturvårdsverket · 2026-10-25');
    expect(rows('National interests')[0]).toHaveTextContent('Boverket (sammanställning) · 2026-10-25');
    expect(rows('Ancient remains')[0]).toHaveTextContent('Riksantikvarieämbetet · 2026-10-25');
  });
});
