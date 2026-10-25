// Unit tests for components/place/PlaceCard.tsx.
import { render, screen, within } from '@testing-library/react';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';

import PlaceCard from '@/components/place/PlaceCard';

import { kaboOutside, kungsangen, nothingAround, notCovered, propertyUnavailable, street } from '../../../mocks/place';

function card(profile = kungsangen) {
  render(createElement(PlaceCard, { profile }));
}

describe('place card', () => {
  it('shows the property', () => {
    /** The card names the property at the pin and its kommun. */
    card();
    expect(screen.getByRole('heading', { name: 'Uppsala Kungsängen 7:8' })).toBeInTheDocument();
    expect(screen.getByText('Kommun: Uppsala')).toBeInTheDocument();
  });

  it("shows the property's addresses under its name", () => {
    /** The kommun's addresses on the property tell the user which house the designation is. */
    card({ ...kungsangen, property: { ...kungsangen.property!, addresses: ['Kungsgatan 63A', 'Kungsgatan 63B'] } });
    expect(screen.getByText('Kungsgatan 63A, Kungsgatan 63B')).toBeInTheDocument();
  });

  it('shortens a long address list', () => {
    const addresses = Array.from({ length: 9 }, (_, i) => `Vägen ${i + 1}`);
    card({ ...kungsangen, property: { ...kungsangen.property!, addresses } });
    expect(screen.getByText('Vägen 1, Vägen 2, Vägen 3, Vägen 4 and 5 more')).toBeInTheDocument();
  });

  it('lists the plans in force newest first, each with a link to its documents', () => {
    /** Plans come newest laga kraft date first with aktbeteckning, name, date and a document link. */
    card();
    const plans = within(screen.getByRole('list', { name: 'Detaljplaner' })).getAllByRole('listitem');
    const refs = plans.map((item) => item.textContent?.match(/0380-[PO]\d{4}\/\d+/)?.[0]);
    expect(refs).toEqual(['0380-P2012/9', '0380-O2005/1', '0380-P2002/5', '0380-P1990/3']);
    expect(within(plans[2]).getByText('Del av Atle, Kungsängen 7:8')).toBeInTheDocument();
    expect(within(plans[2]).getByText(/2002-01-09/)).toBeInTheDocument();
    expect(within(plans[2]).getByRole('link', { name: /documents/i })).toHaveAttribute(
      'href', 'https://www.uppsala.se/detaljplan/?aktbeteckning=0380-P2002/5');
  });

  it('marks tillägg and områdesbestämmelser among the plans', () => {
    /** A tillägg and områdesbestämmelser are labelled as such in the plan list. */
    card();
    const plans = within(screen.getByRole('list', { name: 'Detaljplaner' })).getAllByRole('listitem');
    expect(plans[0]).toHaveTextContent('Tillägg');
    expect(plans[1]).toHaveTextContent('Områdesbestämmelser');
  });

  it('lists the land-use zones with code and wording, as interpreted boundaries', () => {
    /** Each zone shows its code, wording, share of the property and the interpreted-boundary caveat. */
    card();
    const zones = within(screen.getByRole('list', { name: 'Användning' })).getAllByRole('listitem');
    expect(zones[0]).toHaveTextContent('BCK');
    expect(zones[0]).toHaveTextContent('Bostäder, Centrumfunktion, Kontor');
    expect(zones[0]).toHaveTextContent('75 %');
    expect(screen.getAllByText(/interpreted boundaries/i).length).toBeGreaterThan(0);
  });

  it('points to indexed provisions and says when they are not indexed', () => {
    /** A plan with provisions in the corpus says so; the others say the provisions are not indexed. */
    card();
    const plans = within(screen.getByRole('list', { name: 'Detaljplaner' })).getAllByRole('listitem');
    expect(plans[2]).toHaveTextContent(/provisions in the corpus/i);
    expect(plans[3]).toHaveTextContent(/provisions not indexed/i);
  });

  it('shows plans in progress apart, as not binding', () => {
    /** Plans in progress have their own section with their stage and a not-binding label. */
    card();
    const pending = screen.getByRole('list', { name: 'Plans in progress' });
    expect(pending).toHaveTextContent('Kungsängen 7:8 m.fl.');
    expect(pending).toHaveTextContent('Samråd');
    expect(pending).toHaveTextContent(/not binding/i);
  });

  it('says the property is inside a detaljplan', () => {
    /** A property under a plan in force is marked inside a detaljplan. */
    card();
    expect(screen.getByText(/inside a detaljplan/i)).toBeInTheDocument();
  });

  it('says the property is outside a detaljplan', () => {
    /** A property with no plan, in a complete plan source, is marked outside a detaljplan. */
    card(kaboOutside);
    expect(screen.getByText(/outside a detaljplan/i)).toBeInTheDocument();
  });

  it('asks to move the pin when there is no property', () => {
    /** A pin on a street, park or water says so and asks to move the pin. */
    card(street);
    expect(screen.getByText(/no property here/i)).toBeInTheDocument();
    expect(screen.getByText(/move the pin/i)).toBeInTheDocument();
  });

  it('says the place is not covered yet outside the pilot kommuner', () => {
    /** Outside the pilot kommuner the card says the place is not covered yet. */
    card(notCovered);
    expect(screen.getByText(/not covered yet/i)).toBeInTheDocument();
  });

  it('says when the property service is unavailable', () => {
    /** A failed property lookup is shown as unavailable, not as no property. */
    card(propertyUnavailable);
    expect(screen.getByText(/property lookup is unavailable/i)).toBeInTheDocument();
  });

  it('names the source and date of every row', () => {
    /** Every plan, zone and plan in progress shows its source and snapshot date. */
    card();
    const rows = [
      ...within(screen.getByRole('list', { name: 'Detaljplaner' })).getAllByRole('listitem'),
      ...within(screen.getByRole('list', { name: 'Användning' })).getAllByRole('listitem'),
      ...within(screen.getByRole('list', { name: 'Plans in progress' })).getAllByRole('listitem'),
    ];
    for (const item of rows) expect(item).toHaveTextContent('Uppsala kommun · 2026-10-25');
  });

  it('says it is registry data, not a decision', () => {
    /** The card carries the registry-data note. */
    card();
    expect(screen.getByText(/Registry data, not a decision/)).toBeInTheDocument();
  });
});

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
