'use client';

import type { ReactNode } from 'react';
import {
  Castle, Clock, ExternalLink, FileText, Landmark, LayoutGrid, Leaf, type LucideIcon, Bird, Scale, Stamp,
  TriangleAlert, Waves,
} from 'lucide-react';

import type { PlaceFeature, PlacePermit, PlaceProfile, SectionStatus } from '@/lib/place';

const KIND_LABEL: Record<string, string> = {
  plan_addition: 'Tillägg',
  area_regulations: 'Områdesbestämmelser',
};

const DETALJPLAN_STATUS: Record<PlaceProfile['detaljplan'], { text: string; tone: string }> = {
  inside: { text: 'Inside a detaljplan', tone: 'bg-blue-500/10 text-blue-700 dark:text-blue-300' },
  outside: { text: 'Outside a detaljplan', tone: 'bg-zinc-500/10 text-zinc-700 dark:text-zinc-300' },
  unknown: {
    text: 'No digital detaljplan found: an older plan may apply',
    tone: 'bg-amber-500/15 text-amber-800 dark:text-amber-300',
  },
};

// iOS-style icon tiles: one colour per kind of row
const TILE: Record<string, { icon: LucideIcon; colour: string }> = {
  plan: { icon: FileText, colour: 'bg-orange-500' },
  zone: { icon: LayoutGrid, colour: 'bg-emerald-500' },
  pending: { icon: Clock, colour: 'bg-zinc-400' },
  protected: { icon: Leaf, colour: 'bg-green-600' },
  natura2000: { icon: Bird, colour: 'bg-teal-500' },
  national_interest: { icon: Landmark, colour: 'bg-indigo-500' },
  ancient_remain: { icon: Castle, colour: 'bg-amber-700' },
  strandskydd: { icon: Waves, colour: 'bg-sky-500' },
  permit: { icon: Stamp, colour: 'bg-blue-500' },
  consideration: { icon: Scale, colour: 'bg-zinc-500' },
};

function Tile({ kind }: { kind: keyof typeof TILE }) {
  const { icon: Icon, colour } = TILE[kind];
  return (
    <span aria-hidden className={`mt-0.5 grid size-7 shrink-0 place-items-center rounded-[8px] text-white ${colour}`}>
      <Icon size={15} strokeWidth={2.25} />
    </span>
  );
}

function SourceLine({ row }: { row: PlaceFeature }) {
  return <p className="mt-1 text-[11px] text-zinc-400 dark:text-zinc-500">{`${row.source} · ${row.fetched}`}</p>;
}

function DocLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer"
       className="inline-flex items-center gap-1 font-medium text-blue-600 hover:underline dark:text-blue-400">
      {children} <ExternalLink size={11} aria-hidden />
    </a>
  );
}

function Row({ kind, children }: { kind: keyof typeof TILE; children: ReactNode }) {
  return (
    <li className="flex gap-3 px-3 py-2.5 text-[13px] leading-snug">
      <Tile kind={kind} />
      <div className="min-w-0 flex-1">{children}</div>
    </li>
  );
}

function Title({ children }: { children: ReactNode }) {
  return <p className="font-semibold text-zinc-900 dark:text-zinc-50">{children}</p>;
}

function Meta({ children }: { children: ReactNode }) {
  return (
    <div className="mt-0.5 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-xs text-zinc-500 dark:text-zinc-400">
      {children}
    </div>
  );
}

function SectionTitle({ children }: { children: ReactNode }) {
  return <h4 className="px-1 text-[13px] font-semibold text-zinc-500 dark:text-zinc-400">{children}</h4>;
}

// A grouped list in the iOS style: a small header over a rounded group of rows
function Section({ title, status = 'ok', count, children }: {
  title: string; status?: SectionStatus; count: number; children: ReactNode;
}) {
  let body: ReactNode;
  if (status === 'unavailable') {
    body = (
      <p className="flex items-center gap-2 px-3 py-2.5 text-[13px] text-amber-700 dark:text-amber-300">
        <TriangleAlert size={14} aria-hidden /> The source could not be reached: not checked.
      </p>
    );
  } else if (count === 0) {
    body = <p className="px-3 py-2.5 text-[13px] text-zinc-500 dark:text-zinc-400">None found.</p>;
  } else {
    body = <ul aria-label={title} className="divide-y divide-zinc-200/70 dark:divide-white/10">{children}</ul>;
  }
  return (
    <section aria-label={title} className="space-y-1.5">
      <SectionTitle>{title}</SectionTitle>
      <div className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-black/5 dark:bg-zinc-800/70 dark:ring-white/10">
        {body}
      </div>
    </section>
  );
}

function PlanRow({ plan }: { plan: PlaceFeature }) {
  return (
    <Row kind="plan">
      <div className="flex items-baseline gap-2">
        {KIND_LABEL[plan.kind] && (
          <span className="rounded-md bg-orange-500/10 px-1.5 py-px text-[11px] font-semibold text-orange-700 dark:text-orange-300">
            {KIND_LABEL[plan.kind]}
          </span>
        )}
        <span className="font-mono text-[11px] text-zinc-500 dark:text-zinc-400">{plan.ref}</span>
      </div>
      <Title>{plan.name}</Title>
      <Meta>
        {plan.date && <span>{`Laga kraft ${plan.date}`}</span>}
        <span>{plan.provisions_indexed ? 'Provisions in the corpus' : 'Provisions not indexed'}</span>
        {plan.url && <DocLink href={plan.url}>Plan documents</DocLink>}
      </Meta>
      <SourceLine row={plan} />
    </Row>
  );
}

function ZoneRow({ zone }: { zone: PlaceFeature }) {
  return (
    <Row kind="zone">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-[12px] font-semibold text-emerald-700 dark:text-emerald-300">{zone.ref}</span>
        {zone.share != null && (
          <span className="text-xs text-zinc-500 dark:text-zinc-400">{`${Math.round(zone.share * 100)} % of the property`}</span>
        )}
      </div>
      <p className="text-zinc-800 dark:text-zinc-200">{zone.name}</p>
      {zone.note && <Meta><span>Interpreted boundaries</span></Meta>}
      <SourceLine row={zone} />
    </Row>
  );
}

function PendingRow({ plan }: { plan: PlaceFeature }) {
  return (
    <Row kind="pending">
      <Title>{plan.name}</Title>
      <Meta>
        <span className="rounded-md bg-zinc-500/10 px-1.5 py-px text-[11px] font-semibold text-zinc-600 dark:text-zinc-300">
          Not binding
        </span>
        {plan.status && <span>{plan.status}</span>}
        {plan.text && <span>{plan.text}</span>}
      </Meta>
      <SourceLine row={plan} />
    </Row>
  );
}

function ProtectedRow({ area }: { area: PlaceFeature }) {
  return (
    <Row kind="protected">
      <p className="text-xs font-medium text-green-700 dark:text-green-400">{area.type}</p>
      <Title>{area.name}</Title>
      <Meta>
        {area.authority && <span>{`Decided by ${area.authority}`}</span>}
        {area.date && <span>{area.date}</span>}
        {area.url && <DocLink href={area.url}>Decision</DocLink>}
      </Meta>
      <SourceLine row={area} />
    </Row>
  );
}

function NaturaRow({ site }: { site: PlaceFeature }) {
  return (
    <Row kind="natura2000">
      <Title>{site.name}</Title>
      <Meta>
        <span className="font-mono">{site.ref}</span>
        {site.type && <span>{site.type}</span>}
        {site.url && <DocLink href={site.url}>Site description</DocLink>}
      </Meta>
      <SourceLine row={site} />
    </Row>
  );
}

function InterestRow({ interest }: { interest: PlaceFeature }) {
  return (
    <Row kind="national_interest">
      <p className="text-xs font-medium text-indigo-700 dark:text-indigo-300">{interest.type}</p>
      <Title>{interest.name}</Title>
      <Meta>
        {interest.law && <span>{interest.law}</span>}
        {interest.url && <DocLink href={interest.url}>Description</DocLink>}
      </Meta>
      <SourceLine row={interest} />
    </Row>
  );
}

function RemainRow({ remain }: { remain: PlaceFeature }) {
  return (
    <Row kind="ancient_remain">
      <Title>{remain.type}</Title>
      <Meta>
        <span className="font-mono">{remain.ref}</span>
        {remain.status && <span>{remain.status}</span>}
        {remain.url && <DocLink href={remain.url}>Fornsök</DocLink>}
      </Meta>
      <SourceLine row={remain} />
    </Row>
  );
}

function PermitRow({ permit }: { permit: PlacePermit }) {
  return (
    <Row kind={permit.kind}>
      {permit.kind === 'consideration' && (
        <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Consideration</p>
      )}
      <Title>{permit.title}</Title>
      <Meta>
        <span className="font-mono">{permit.law}</span>
        <span>{permit.authority}</span>
      </Meta>
      <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{permit.reason}</p>
    </Row>
  );
}

function Strandskydd({ strandskydd }: { strandskydd: PlaceProfile['strandskydd'] }) {
  return (
    <section aria-label="Strandskydd" className="space-y-1.5">
      <SectionTitle>Strandskydd</SectionTitle>
      <div className="flex gap-3 rounded-xl bg-white px-3 py-2.5 text-[13px] shadow-sm ring-1 ring-black/5 dark:bg-zinc-800/70 dark:ring-white/10">
        <Tile kind="strandskydd" />
        <div>
          <Title>Not checked</Title>
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{strandskydd.reason}</p>
          <p className="mt-1 text-xs text-zinc-700 dark:text-zinc-300">{strandskydd.note}</p>
        </div>
      </div>
    </section>
  );
}

function Headline({ profile }: { profile: PlaceProfile }) {
  if (!profile.covered) {
    return <p className="text-sm text-zinc-600 dark:text-zinc-300">This place is not covered yet: the map covers Uppsala for now.</p>;
  }
  return (
    <div className="space-y-1.5">
      <h3 className="text-[22px] font-bold leading-tight tracking-[-0.02em] text-zinc-900 dark:text-white">
        {profile.property?.designation ?? 'Pinned point'}
      </h3>
      {profile.kommun && <p className="text-[13px] text-zinc-500 dark:text-zinc-400">{`Kommun: ${profile.kommun.name}`}</p>}
      {profile.property_status === 'none' && (
        <p className="text-[13px] text-amber-700 dark:text-amber-300">
          No property here: the pin is on a street, a park or water. Move the pin onto a property.
        </p>
      )}
      {profile.property_status === 'unavailable' && (
        <p className="text-[13px] text-amber-700 dark:text-amber-300">
          The property lookup is unavailable right now: the plans below are those at the pin.
        </p>
      )}
      <p className={`inline-block rounded-full px-2.5 py-1 text-xs font-semibold ${DETALJPLAN_STATUS[profile.detaljplan].tone}`}>
        {DETALJPLAN_STATUS[profile.detaljplan].text}
      </p>
    </div>
  );
}

/**
 * The place card of a pinned point: the property, the plans in force (newest first, with tillägg and
 * områdesbestämmelser), the land-use zones, the plans in progress (not binding), the protected areas, Natura 2000
 * sites, national interests and ancient remains on the property, strandskydd (not checked yet) and the likely
 * permits, with the source and date of every row and the note that this is registry data, not a decision.
 */
export default function PlaceCard({ profile }: { profile: PlaceProfile }) {
  const status = profile.section_status;
  return (
    <div className="space-y-5">
      <Headline profile={profile} />
      {profile.plans.length > 0 && (
        <Section title="Detaljplaner" count={profile.plans.length}>
          {profile.plans.map((plan) => <PlanRow key={`${plan.layer}-${plan.ref}`} plan={plan} />)}
        </Section>
      )}
      {profile.zones.length > 0 && (
        <Section title="Användning" count={profile.zones.length}>
          {profile.zones.map((zone, i) => <ZoneRow key={`${zone.ref}-${i}`} zone={zone} />)}
        </Section>
      )}
      {profile.pending_plans.length > 0 && (
        <Section title="Plans in progress" count={profile.pending_plans.length}>
          {profile.pending_plans.map((plan, i) => <PendingRow key={`${plan.ref}-${i}`} plan={plan} />)}
        </Section>
      )}
      {profile.covered && (
        <>
          <Section title="Protected areas" status={status.protected_areas} count={profile.protected_areas.length}>
            {profile.protected_areas.map((area, i) => <ProtectedRow key={`${area.ref}-${i}`} area={area} />)}
          </Section>
          <Section title="Natura 2000" status={status.natura2000} count={profile.natura2000.length}>
            {profile.natura2000.map((site, i) => <NaturaRow key={`${site.ref}-${i}`} site={site} />)}
          </Section>
          <Section title="National interests" status={status.national_interests} count={profile.national_interests.length}>
            {profile.national_interests.map((interest, i) => <InterestRow key={`${interest.layer}-${i}`} interest={interest} />)}
          </Section>
          <Section title="Ancient remains" status={status.ancient_remains} count={profile.ancient_remains.length}>
            {profile.ancient_remains.map((remain, i) => <RemainRow key={`${remain.ref}-${i}`} remain={remain} />)}
          </Section>
          <Strandskydd strandskydd={profile.strandskydd} />
          <Section title="Likely permits" count={profile.permits.length}>
            {profile.permits.map((permit, i) => <PermitRow key={`${permit.title}-${i}`} permit={permit} />)}
          </Section>
        </>
      )}
      <div className="space-y-1 px-1 text-[11px] leading-relaxed text-zinc-500 dark:text-zinc-400">
        {profile.notes.map((note) => <p key={note}>{note}</p>)}
      </div>
    </div>
  );
}
