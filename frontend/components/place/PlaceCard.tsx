'use client';

import type { PlaceProfile } from '@/lib/place';

/**
 * The place card of a pinned point: the property, the plans in force (newest first, with tillägg and
 * områdesbestämmelser), the land-use zones, the plans in progress (not binding), inside or outside a detaljplan,
 * and the source and date of every row, under the note that this is registry data, not a decision.
 */
export default function PlaceCard({ profile }: { profile: PlaceProfile }) {
  void profile;
  throw new Error('not implemented');
}
