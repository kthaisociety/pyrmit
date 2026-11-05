'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Layers, Loader2, X } from 'lucide-react';

import PlaceCard from '@/components/place/PlaceCard';
import { GLASS } from '@/components/place/glass';
import PlaceMap, { type MapView, type PlaceOutline, type ReviewLayers } from '@/components/place/PlaceMap';
import PlaceSearch from '@/components/place/PlaceSearch';
import {
  COVERAGE_COLOURS, MATCH_COLOURS, fetchPlaceCoverage, fetchPlaceProfile, fetchPlansInView, fetchReviewCoverage,
  type Pin, type PlaceProfile, type PlaceSearchResult, type ReviewCoverage, type ReviewPlans,
} from '@/lib/place';

export interface PlacePanelProps {
  pin: Pin | null;
  onPinChange: (pin: Pin) => void;
  onClose: () => void;
  onProfile?: (profile: PlaceProfile) => void; // the profile of the pin, once it is looked up
}

type Lookup = { pin: Pin; profile: PlaceProfile | null; error: string | null };

// The zoom from which the review mode fetches the plans in view (about a kommun's size, see ADR-0008); below it the
// map shows the kommuner coloured by coverage only
export const REVIEW_PLANS_ZOOM = 10;

// The system font (SF Pro on Apple devices), as in Apple Maps
const SYSTEM_FONT = '[font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif]';

function outlinesOf(profile: PlaceProfile | null): PlaceOutline[] {
  if (!profile) return [];
  return [
    ...(profile.property ? [{ id: 'property', kind: 'property' as const, geometry: profile.property.geometry }] : []),
    ...profile.plans.map((plan, i) => ({ id: `plan-${i}`, kind: 'plan' as const, geometry: plan.geometry })),
    ...profile.zones.map((zone, i) => ({ id: `zone-${i}`, kind: 'zone' as const, geometry: zone.geometry })),
  ];
}

// The share of the panel the card covers: expanded from 38 % of the height, collapsed or empty a strip
function sheetCover(hasCard: boolean, expanded: boolean): number {
  if (!hasCard) return 0.1;
  return expanded ? 0.6 : 0.16;
}

// A search match on the map, waiting for "Pin here" before the pin moves
function ProposalCard({ proposal, onCancel, onConfirm }: {
  proposal: PlaceSearchResult; onCancel: () => void; onConfirm: () => void;
}) {
  return (
    <div className={`flex items-center gap-2 rounded-xl px-3 py-2 ${GLASS}`}>
      <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-zinc-900 dark:text-zinc-50">
        {proposal.label}
      </span>
      <button
        type="button"
        onClick={onCancel}
        className="rounded-lg px-2 py-1 text-[13px] text-zinc-600 transition-transform duration-100 hover:bg-black/5 active:scale-95 dark:text-zinc-300"
      >
        Cancel
      </button>
      <button
        type="button"
        onClick={onConfirm}
        className="rounded-lg bg-blue-500 px-3 py-1 text-[13px] font-semibold text-white shadow-sm transition-transform duration-100 hover:bg-blue-600 active:scale-95"
      >
        Pin here
      </button>
    </div>
  );
}

function LegendRow({ colour, label }: { colour: string; label: string }) {
  return (
    <li className="flex items-center gap-1.5">
      <span className="size-2.5 shrink-0 rounded-sm" style={{ backgroundColor: colour }} aria-hidden />
      {label}
    </li>
  );
}

// What the review mode's colours mean, how far the coverage goes and what could not be shown
function ReviewCard({ coverage, plans, zoomedIn, error }: {
  coverage: ReviewCoverage | null; plans: ReviewPlans | null; zoomedIn: boolean; error: string | null;
}) {
  const covered = coverage?.features.filter((kommun) => kommun.properties.covered).length ?? 0;
  return (
    <div className={`space-y-1 rounded-xl px-3 py-2 text-[12px] text-zinc-700 dark:text-zinc-200 ${GLASS}`}>
      {coverage && (
        <p className="font-semibold text-zinc-900 dark:text-zinc-50">
          {`${covered} of ${coverage.features.length} kommuner with plan polygons`}
        </p>
      )}
      {error && <p role="alert" className="text-red-600 dark:text-red-400">{error}</p>}
      {zoomedIn ? (
        <ul aria-label="Match levels" className="flex flex-wrap gap-x-3">
          <LegendRow colour={MATCH_COLOURS.link} label="Link" />
          <LegendRow colour={MATCH_COLOURS.akt} label="Akt" />
          <LegendRow colour={MATCH_COLOURS.name} label="Name" />
          <LegendRow colour={MATCH_COLOURS.none} label="No document" />
        </ul>
      ) : (
        <ul aria-label="Coverage" className="flex flex-wrap gap-x-3">
          <LegendRow colour={COVERAGE_COLOURS.covered} label="Has polygons" />
          <LegendRow colour={COVERAGE_COLOURS.not_covered} label="None" />
        </ul>
      )}
      {!zoomedIn && <p className="text-zinc-500 dark:text-zinc-400">Zoom in on a kommun to see its plans.</p>}
      {zoomedIn && plans?.truncated && (
        <p className="text-amber-700 dark:text-amber-400">More plans here than are drawn: zoom in to see every plan.</p>
      )}
    </div>
  );
}

function union(boxes: [number, number, number, number][]): [number, number, number, number] | null {
  if (boxes.length === 0) return null;
  return [
    Math.min(...boxes.map((box) => box[0])), Math.min(...boxes.map((box) => box[1])),
    Math.max(...boxes.map((box) => box[2])), Math.max(...boxes.map((box) => box[3])),
  ];
}

/**
 * The map panel beside the conversation (labelled "Map"): a click on the map moves the pin, and the place card of
 * the pin is fetched and shown in a sheet over the map, with the property, plans and zones outlined on it.
 */
export default function PlacePanel({ pin, onPinChange, onClose, onProfile }: PlacePanelProps) {
  const [lookup, setLookup] = useState<Lookup | null>(null);
  const onProfileRef = useRef(onProfile);
  const [bounds, setBounds] = useState<[number, number, number, number] | null>(null);
  const [expanded, setExpanded] = useState(true);
  // A search match waiting for the user's confirmation: the current pin and card stay until then
  const [proposal, setProposal] = useState<PlaceSearchResult | null>(null);
  // The review mode, off until asked for (ADR-0008): the coverage once on, the plans of the view once zoomed in
  const [reviewOn, setReviewOn] = useState(false);
  const [view, setView] = useState<MapView | null>(null);
  const [coverage, setCoverage] = useState<ReviewCoverage | null>(null);
  const [plans, setPlans] = useState<ReviewPlans | null>(null);
  const [coverageError, setCoverageError] = useState<string | null>(null);
  const [plansError, setPlansError] = useState<string | null>(null);

  useEffect(() => {
    fetchPlaceCoverage()
      .then((kommuner) => setBounds(union(kommuner.map((kommun) => kommun.bbox))))
      .catch(() => setBounds(null)); // the map then opens on all of Sweden
  }, []);

  useEffect(() => {
    onProfileRef.current = onProfile;
  }, [onProfile]);

  // A late answer for a pin the user has already moved is dropped
  useEffect(() => {
    if (!pin) return;
    let current = true;
    fetchPlaceProfile(pin)
      .then((profile) => {
        if (!current) return;
        setLookup({ pin, profile, error: null });
        onProfileRef.current?.(profile);
      })
      .catch((err: Error) => current && setLookup({ pin, profile: null, error: err.message }));
    return () => {
      current = false;
    };
  }, [pin]);

  useEffect(() => {
    if (!reviewOn) return;
    let current = true;
    fetchReviewCoverage()
      .then((found) => {
        if (!current) return;
        setCoverage(found);
        setCoverageError(null);
      })
      .catch((err: Error) => current && setCoverageError(`Could not fetch the coverage: ${err.message}`));
    return () => {
      current = false;
    };
  }, [reviewOn]);

  const plansBox = reviewOn && view && view.zoom >= REVIEW_PLANS_ZOOM ? view.bbox : null;
  // A late answer for a view the user has already left is dropped
  useEffect(() => {
    if (!plansBox) return;
    let current = true;
    fetchPlansInView(plansBox)
      .then((found) => {
        if (!current) return;
        setPlans(found);
        setPlansError(null);
      })
      .catch((err: Error) => current && setPlansError(`Could not fetch the plans: ${err.message}`));
    return () => {
      current = false;
    };
  }, [plansBox]);

  const review = useMemo<ReviewLayers | null>(
    () => (reviewOn ? { coverage, plans: plansBox ? plans : null } : null), [reviewOn, coverage, plans, plansBox]);

  const settled = lookup !== null && pin !== null && lookup.pin === pin;
  const shown = pin ? lookup : null; // keep the previous card, dimmed, while the next one loads
  const outlines = useMemo(() => outlinesOf(shown?.profile ?? null), [shown]);
  const hasCard = Boolean(pin);

  return (
    <aside
      aria-label="Map"
      className={`place-map relative h-full w-[440px] shrink-0 overflow-hidden border-l border-zinc-200 bg-zinc-100 ${SYSTEM_FONT} motion-safe:animate-[slide-in-right_280ms_cubic-bezier(0.32,0.72,0,1)] dark:border-zinc-800 dark:bg-zinc-900`}
    >
      <div className="absolute inset-0">
        <PlaceMap pin={pin} outlines={outlines} bounds={bounds} bottomInset={sheetCover(hasCard, expanded)}
                  proposal={proposal} review={review} onMapClick={onPinChange} onViewChange={setView} />
      </div>

      <div className="absolute left-3 right-14 top-3 z-20 space-y-1.5">
        <PlaceSearch onPropose={setProposal} />
        {proposal && (
          <ProposalCard
            proposal={proposal}
            onCancel={() => setProposal(null)}
            onConfirm={() => {
              onPinChange({ lat: proposal.lat, lon: proposal.lon });
              setProposal(null);
            }}
          />
        )}
      </div>

      {reviewOn && (
        <div className={`absolute left-3 right-14 z-10 ${proposal ? 'top-[112px]' : 'top-[84px]'}`}>
          <ReviewCard coverage={coverage} plans={plans} zoomedIn={plansBox !== null}
                      error={coverageError ?? (plansBox ? plansError : null)} />
        </div>
      )}

      <button
        type="button"
        onClick={() => setReviewOn((on) => !on)}
        aria-label="Review plan coverage"
        aria-pressed={reviewOn}
        title="Review plan coverage"
        className={`absolute right-3 top-[132px] z-10 grid size-8 place-items-center rounded-full transition-transform duration-100 active:scale-90 ${
          reviewOn ? 'bg-blue-500 text-white shadow-sm' : `text-zinc-600 dark:text-zinc-300 ${GLASS}`
        }`}
      >
        <Layers size={15} aria-hidden />
      </button>

      <button
        type="button"
        onClick={onClose}
        aria-label="Close map"
        className={`absolute right-3 top-3 z-10 grid size-8 place-items-center rounded-full text-zinc-600 transition-transform duration-100 active:scale-90 dark:text-zinc-300 ${GLASS}`}
      >
        <X size={16} strokeWidth={2.5} />
      </button>

      <div
        className={`absolute inset-x-2 bottom-2 z-10 flex flex-col overflow-hidden rounded-[22px] transition-[top] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] motion-reduce:transition-none ${GLASS} ${
          hasCard ? (expanded ? 'top-[38%]' : 'top-[calc(100%-7.5rem)]') : 'top-[calc(100%-4.25rem)]'
        }`}
      >
        <button
          type="button"
          onClick={() => setExpanded((open) => !open)}
          disabled={!hasCard}
          aria-label={expanded ? 'Collapse place card' : 'Expand place card'}
          aria-expanded={expanded}
          className="flex shrink-0 justify-center pb-1 pt-2 disabled:cursor-default"
        >
          <span className="h-[5px] w-9 rounded-full bg-zinc-400/60 dark:bg-zinc-500/60" />
        </button>
        <div className="flex-1 overflow-y-auto overscroll-contain px-4 pb-4">
          {!pin && (
            <p className="py-1 text-[13px] text-zinc-500 dark:text-zinc-400">Click the map to pin a place in Uppsala.</p>
          )}
          {pin && !settled && (
            <p role="status" className="mb-3 flex items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
              <Loader2 size={12} className="animate-spin" aria-hidden /> Looking up the place…
            </p>
          )}
          {shown?.error && settled && (
            <p role="alert" className="text-[13px] text-red-600 dark:text-red-400">{`Could not look up this place: ${shown.error}`}</p>
          )}
          {shown?.profile && (
            <div className={settled ? '' : 'opacity-50 transition-opacity'}>
              <PlaceCard profile={shown.profile} />
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
