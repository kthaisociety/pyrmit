'use client';

import type { ReactNode } from 'react';
import { ExternalLink } from 'lucide-react';

import type { PlaceFeature, PlaceProfile } from '@/lib/place';

const KIND_LABEL: Record<string, string> = {
  plan_addition: 'Tillägg',
  area_regulations: 'Områdesbestämmelser',
};

const DETALJPLAN_STATUS: Record<PlaceProfile['detaljplan'], { text: string; tone: string }> = {
  inside: { text: 'Inside a detaljplan', tone: 'bg-blue-50 text-blue-700 dark:bg-blue-950/60 dark:text-blue-300' },
  outside: { text: 'Outside a detaljplan', tone: 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300' },
  unknown: {
    text: 'No digital detaljplan found: an older plan may apply',
    tone: 'bg-amber-50 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300',
  },
};

function SourceLine({ row }: { row: PlaceFeature }) {
  return <p className="mt-1 text-[11px] text-zinc-400 dark:text-zinc-500">{`${row.source} · ${row.fetched}`}</p>;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h4 className="text-xs font-semibold text-zinc-500 dark:text-zinc-400">{title}</h4>
      <ul aria-label={title} className="divide-y divide-zinc-100 rounded-xl border border-zinc-200 bg-white dark:divide-zinc-800 dark:border-zinc-800 dark:bg-zinc-900">
        {children}
      </ul>
    </section>
  );
}

function PlanRow({ plan }: { plan: PlaceFeature }) {
  return (
    <li className="px-3 py-2.5 text-sm">
      <div className="flex items-baseline gap-2">
        {KIND_LABEL[plan.kind] && (
          <span className="rounded-md bg-orange-50 px-1.5 py-0.5 text-[11px] font-medium text-orange-700 dark:bg-orange-950/60 dark:text-orange-300">
            {KIND_LABEL[plan.kind]}
          </span>
        )}
        <span className="font-mono text-xs text-zinc-500 dark:text-zinc-400">{plan.ref}</span>
      </div>
      <p className="mt-0.5 font-medium text-zinc-900 dark:text-zinc-100">{plan.name}</p>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500 dark:text-zinc-400">
        {plan.date && <span>{`Laga kraft ${plan.date}`}</span>}
        <span>{plan.provisions_indexed ? 'Provisions in the corpus' : 'Provisions not indexed'}</span>
        {plan.url && (
          <a href={plan.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-blue-600 hover:underline dark:text-blue-400">
            Plan documents <ExternalLink size={11} aria-hidden />
          </a>
        )}
      </div>
      <SourceLine row={plan} />
    </li>
  );
}

function ZoneRow({ zone }: { zone: PlaceFeature }) {
  return (
    <li className="px-3 py-2.5 text-sm">
      <div className="flex items-baseline gap-2">
        <span className="rounded-md bg-emerald-50 px-1.5 py-0.5 font-mono text-[11px] font-medium text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300">
          {zone.ref}
        </span>
        {zone.share != null && (
          <span className="text-xs text-zinc-500 dark:text-zinc-400">{`${Math.round(zone.share * 100)} % of the property`}</span>
        )}
      </div>
      <p className="mt-0.5 text-zinc-800 dark:text-zinc-200">{zone.name}</p>
      {zone.note && <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">Interpreted boundaries</p>}
      <SourceLine row={zone} />
    </li>
  );
}

function PendingRow({ plan }: { plan: PlaceFeature }) {
  return (
    <li className="px-3 py-2.5 text-sm">
      <div className="flex items-baseline gap-2">
        <span className="rounded-md bg-zinc-100 px-1.5 py-0.5 text-[11px] font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
          Not binding
        </span>
        {plan.status && <span className="text-xs text-zinc-500 dark:text-zinc-400">{plan.status}</span>}
      </div>
      <p className="mt-0.5 text-zinc-800 dark:text-zinc-200">{plan.name}</p>
      {plan.text && <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{plan.text}</p>}
      <SourceLine row={plan} />
    </li>
  );
}

function Headline({ profile }: { profile: PlaceProfile }) {
  if (!profile.covered) {
    return <p className="text-sm text-zinc-600 dark:text-zinc-300">This place is not covered yet: the map covers Uppsala for now.</p>;
  }
  return (
    <div className="space-y-1">
      <h3 className="text-lg font-semibold tracking-[-0.01em] text-zinc-900 dark:text-zinc-50">
        {profile.property?.designation ?? 'Pinned point'}
      </h3>
      {profile.kommun && <p className="text-xs text-zinc-500 dark:text-zinc-400">{`Kommun: ${profile.kommun.name}`}</p>}
      {profile.property_status === 'none' && (
        <p className="text-sm text-amber-700 dark:text-amber-300">
          No property here: the pin is on a street, a park or water. Move the pin onto a property.
        </p>
      )}
      {profile.property_status === 'unavailable' && (
        <p className="text-sm text-amber-700 dark:text-amber-300">
          The property lookup is unavailable right now: the plans below are those at the pin.
        </p>
      )}
      <p className={`inline-block rounded-full px-2.5 py-1 text-xs font-medium ${DETALJPLAN_STATUS[profile.detaljplan].tone}`}>
        {DETALJPLAN_STATUS[profile.detaljplan].text}
      </p>
    </div>
  );
}

/**
 * The place card of a pinned point: the property, the plans in force (newest first, with tillägg and
 * områdesbestämmelser), the land-use zones, the plans in progress (not binding), inside or outside a detaljplan,
 * and the source and date of every row, under the note that this is registry data, not a decision.
 */
export default function PlaceCard({ profile }: { profile: PlaceProfile }) {
  return (
    <div className="space-y-5">
      <Headline profile={profile} />
      {profile.plans.length > 0 && (
        <Section title="Detaljplaner">
          {profile.plans.map((plan) => <PlanRow key={`${plan.layer}-${plan.ref}`} plan={plan} />)}
        </Section>
      )}
      {profile.zones.length > 0 && (
        <Section title="Användning">
          {profile.zones.map((zone, i) => <ZoneRow key={`${zone.ref}-${i}`} zone={zone} />)}
        </Section>
      )}
      {profile.pending_plans.length > 0 && (
        <Section title="Plans in progress">
          {profile.pending_plans.map((plan, i) => <PendingRow key={`${plan.ref}-${i}`} plan={plan} />)}
        </Section>
      )}
      <div className="space-y-1 border-t border-zinc-200 pt-3 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
        {profile.notes.map((note) => <p key={note}>{note}</p>)}
      </div>
    </div>
  );
}
