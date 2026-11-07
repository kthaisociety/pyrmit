'use client';

import 'maplibre-gl/dist/maplibre-gl.css';
import { useEffect, useRef, useState } from 'react';
import type { ExpressionSpecification, GeoJSONSource, Map as MapLibreMap, MapMouseEvent, Marker,
              Popup } from 'maplibre-gl';

import type { MessageKey } from '@/lib/messages';
import { COVERAGE_COLOURS, MATCH_COLOURS, type BBox, type Pin, type ReviewCoverage, type ReviewPlanProperties,
         type ReviewPlans } from '@/lib/place';
import { useLanguage } from '@/lib/i18n';

export interface PlaceOutline {
  id: string;
  kind: 'property' | 'plan' | 'zone';
  geometry: GeoJSON.Geometry;
}

// What the map shows; reported after every move, so the panel can fetch what the view needs
export interface MapView {
  bbox: BBox;
  zoom: number;
}

// The review mode's layers, fetched by the panel (ADR-0009): the kommuner coloured by coverage, and the plans in view
// coloured by match level (link, akt, name, none). A click on a plan shows its aktbeteckning, name and match level
// instead of moving the pin.
export interface ReviewLayers {
  coverage: ReviewCoverage | null;
  plans: ReviewPlans | null;
}

export interface PlaceMapProps {
  pin: Pin | null;
  outlines: PlaceOutline[]; // drawn over the base map: the property, its plans and zones
  bounds?: [number, number, number, number] | null; // west, south, east, north: first view
  bottomInset?: number; // share of the map's height covered from below (the place card): the view centres above it
  proposal?: Pin | null; // a proposed pin (from the search), shown apart from the pin until the user confirms it
  review?: ReviewLayers | null; // the review mode's layers; null (the default) draws none and the map is as before
  onMapClick: (pin: Pin) => void;
  onViewChange?: (view: MapView) => void; // the view once the map is up and after every move
}

// OpenFreeMap: OpenStreetMap vector tiles, free and keyless; Positron is the light, quiet style
const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron';
const SWEDEN: [number, number, number, number] = [10.5, 55.0, 24.5, 69.5];
const OUTLINES = 'place-outlines';
const REVIEW_KOMMUNER = 'review-kommuner';
const REVIEW_PLANS = 'review-plans';
const REVIEW_PLANS_FILL = `${REVIEW_PLANS}-fill`;
const PIN_ZOOM = 16;
const EDGE_PX = 24;
const TOP_PX = 56; // the floating close button
// Apple system colours: blue for the property, orange (dashed) for plans, green for land-use zones; one layer per
// kind, drawn zones first so the property's outline stays on top
const KIND_STYLE: { kind: PlaceOutline['kind']; color: string; fill: number; width: number; dash?: number[] }[] = [
  { kind: 'zone', color: '#30d158', fill: 0.06, width: 1 },
  { kind: 'plan', color: '#ff9f0a', fill: 0, width: 1.25, dash: [3, 2] },
  { kind: 'property', color: '#0a84ff', fill: 0.14, width: 2.5 },
];
const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

function featureCollection(outlines: PlaceOutline[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: outlines.map((outline) => ({
      type: 'Feature', geometry: outline.geometry, properties: { id: outline.id, kind: outline.kind },
    })),
  };
}

// MapLibre draws no feature without a geometry: a kommun whose boundary was never fetched is left out
function withGeometry(coverage: ReviewCoverage | null): GeoJSON.FeatureCollection {
  if (!coverage) return EMPTY;
  return { type: 'FeatureCollection',
           features: coverage.features.flatMap((kommun) => (kommun.geometry
             ? [{ type: 'Feature' as const, geometry: kommun.geometry, properties: kommun.properties }] : [])) };
}

function addReviewLayers(map: MapLibreMap) {
  const coverageColour: ExpressionSpecification = ['case', ['get', 'covered'], COVERAGE_COLOURS.covered,
                                                    COVERAGE_COLOURS.not_covered];
  map.addSource(REVIEW_KOMMUNER, { type: 'geojson', data: EMPTY });
  map.addLayer({ id: `${REVIEW_KOMMUNER}-fill`, type: 'fill', source: REVIEW_KOMMUNER,
                 paint: { 'fill-color': coverageColour, 'fill-opacity': 0.16 } });
  map.addLayer({ id: `${REVIEW_KOMMUNER}-line`, type: 'line', source: REVIEW_KOMMUNER,
                 paint: { 'line-color': coverageColour, 'line-width': 1 } });
  const matchColour: ExpressionSpecification = ['match', ['coalesce', ['get', 'match'], 'none'],
                                                'link', MATCH_COLOURS.link, 'akt', MATCH_COLOURS.akt,
                                                'name', MATCH_COLOURS.name, MATCH_COLOURS.none];
  map.addSource(REVIEW_PLANS, { type: 'geojson', data: EMPTY });
  map.addLayer({ id: REVIEW_PLANS_FILL, type: 'fill', source: REVIEW_PLANS,
                 paint: { 'fill-color': matchColour, 'fill-opacity': 0.3 } });
  map.addLayer({ id: `${REVIEW_PLANS}-line`, type: 'line', source: REVIEW_PLANS,
                 paint: { 'line-color': matchColour, 'line-width': 1 } });
}

function addOutlineLayers(map: MapLibreMap) {
  map.addSource(OUTLINES, { type: 'geojson', data: featureCollection([]) });
  for (const style of KIND_STYLE) {
    const filter: ['==', ['get', string], string] = ['==', ['get', 'kind'], style.kind];
    if (style.fill > 0) {
      map.addLayer({ id: `${OUTLINES}-${style.kind}-fill`, type: 'fill', source: OUTLINES, filter,
                     paint: { 'fill-color': style.color, 'fill-opacity': style.fill } });
    }
    map.addLayer({ id: `${OUTLINES}-${style.kind}-line`, type: 'line', source: OUTLINES, filter,
                   paint: { 'line-color': style.color, 'line-width': style.width,
                            ...(style.dash ? { 'line-dasharray': style.dash } : {}) } });
  }
}

/** MapLibre looks for its worker next to its own file, which the bundler moved: emit the worker and point there. */
function pointAtBundledWorker(maplibregl: typeof import('maplibre-gl')) {
  maplibregl.setWorkerUrl(new URL('maplibre-gl/dist/maplibre-gl-worker.mjs', import.meta.url).toString());
}

function padding(map: MapLibreMap, bottomInset: number) {
  return { top: TOP_PX, left: EDGE_PX, right: EDGE_PX, bottom: map.getContainer().clientHeight * bottomInset + EDGE_PX };
}

function viewOf(map: MapLibreMap): MapView {
  const bounds = map.getBounds();
  return { bbox: [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()], zoom: map.getZoom() };
}

// The match levels as the popup words them (the legend's labels, in lower case)
const MATCH_LABEL: Record<string, MessageKey> = { link: 'place.matchLink', akt: 'place.matchAkt', name: 'place.matchName' };

// The plan's aktbeteckning, name and match level, as text (never HTML from the data)
function planPopup(properties: ReviewPlanProperties, t: (key: MessageKey) => string): HTMLElement {
  const root = document.createElement('div');
  root.className = 'space-y-0.5 text-[13px] text-zinc-900';
  const lines = [
    [properties.ref ?? t('place.noAktbeteckning'), 'font-semibold'],
    [properties.name ?? '', ''],
    [`${properties.kommun} · ${properties.match ? matchedBy(properties.match, t) : t('place.noDocumentMatched')}`,
     'text-zinc-500'],
  ];
  for (const [text, className] of lines) {
    if (!text) continue;
    const line = document.createElement('div');
    line.className = className;
    line.textContent = text;
    root.appendChild(line);
  }
  return root;
}

function matchedBy(match: string, t: (key: MessageKey) => string): string {
  const key = MATCH_LABEL[match];
  return t('place.matchedBy').replace('{match}', key ? t(key).toLowerCase() : match);
}

/**
 * The base map (MapLibre, OpenFreeMap tiles) with the pin and the outlines; a click reports the point. In the review
 * mode the kommuner and the plans in view are coloured, and a click on a plan shows what it is instead.
 */
export default function PlaceMap({ pin, outlines, bounds, bottomInset = 0, proposal = null, review = null,
                                   onMapClick, onViewChange }: PlaceMapProps) {
  const { t } = useLanguage();
  const tRef = useRef(t); // the popup, opened from a handler set up once, words itself in the current language
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markerRef = useRef<Marker | null>(null);
  const proposalRef = useRef<Marker | null>(null);
  const popupRef = useRef<Popup | null>(null);
  const onClickRef = useRef(onMapClick);
  const onViewChangeRef = useRef(onViewChange);
  const reviewRef = useRef(review);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    onClickRef.current = onMapClick;
  }, [onMapClick]);
  useEffect(() => {
    onViewChangeRef.current = onViewChange;
  }, [onViewChange]);
  useEffect(() => {
    reviewRef.current = review;
  }, [review]);
  useEffect(() => {
    tRef.current = t;
  }, [t]);

  // One map for the component's life; MapLibre is loaded here so server rendering never imports it
  useEffect(() => {
    let cancelled = false;
    import('maplibre-gl').then((maplibregl) => {
      if (cancelled || !container.current) return;
      pointAtBundledWorker(maplibregl);
      const map = new maplibregl.Map({
        container: container.current, style: STYLE_URL, bounds: SWEDEN, fitBoundsOptions: { padding: 24 },
        attributionControl: false, dragRotate: false, pitchWithRotate: false,
      });
      // Zoom under the panel's close button; the attribution the map's licences require, small, top left (the place
      // card covers the bottom)
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
      map.addControl(new maplibregl.AttributionControl({ compact: false }), 'top-left');
      map.on('click', (event: MapMouseEvent) => {
        if (reviewRef.current?.plans && map.getLayer(REVIEW_PLANS_FILL)) {
          const [plan] = map.queryRenderedFeatures(event.point, { layers: [REVIEW_PLANS_FILL] });
          if (plan) {
            popupRef.current?.remove();
            popupRef.current = new maplibregl.Popup({ closeButton: true, maxWidth: '280px' })
              .setLngLat(event.lngLat).setDOMContent(planPopup(plan.properties as ReviewPlanProperties, tRef.current)).addTo(map);
            return;
          }
        }
        onClickRef.current({ lat: event.lngLat.lat, lon: event.lngLat.lng });
      });
      map.on('moveend', () => onViewChangeRef.current?.(viewOf(map)));
      map.on('load', () => {
        addReviewLayers(map);
        addOutlineLayers(map);
        map.on('mouseenter', REVIEW_PLANS_FILL, () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', REVIEW_PLANS_FILL, () => { map.getCanvas().style.cursor = ''; });
        setReady(true);
        onViewChangeRef.current?.(viewOf(map));
      });
      markerRef.current = new maplibregl.Marker({ color: '#ff375f' });
      proposalRef.current = new maplibregl.Marker({ color: '#8e8e93' }); // grey until the user pins it
      mapRef.current = map;
    });
    return () => {
      cancelled = true;
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  // The visible part of the map is above the place card: keep the view centred there as the card moves (set at
  // once the first time, so it cannot race the first view; animated after)
  const insetSet = useRef(false);
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    if (insetSet.current) {
      map.easeTo({ padding: padding(map, bottomInset), duration: 300 });
    } else {
      map.setPadding(padding(map, bottomInset));
      insetSet.current = true;
    }
  }, [ready, bottomInset]);

  useEffect(() => {
    const map = mapRef.current;
    if (ready && map && bounds && !pin) map.fitBounds(bounds, { padding: padding(map, bottomInset), duration: 0 });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the card moving must not refit the kommun
  }, [ready, bounds, pin]);

  useEffect(() => {
    const map = mapRef.current;
    const marker = markerRef.current;
    if (!ready || !map || !marker) return;
    if (!pin) {
      marker.remove();
      return;
    }
    marker.setLngLat([pin.lon, pin.lat]).addTo(map);
    if (map.getZoom() < PIN_ZOOM) map.easeTo({ center: [pin.lon, pin.lat], zoom: PIN_ZOOM, duration: 400 });
  }, [ready, pin]);

  useEffect(() => {
    const map = mapRef.current;
    const marker = proposalRef.current;
    if (!ready || !map || !marker) return;
    if (!proposal) {
      marker.remove();
      return;
    }
    marker.setLngLat([proposal.lon, proposal.lat]).addTo(map);
    map.easeTo({ center: [proposal.lon, proposal.lat], zoom: Math.max(map.getZoom(), PIN_ZOOM), duration: 500 });
  }, [ready, proposal]);

  useEffect(() => {
    if (!ready) return;
    (mapRef.current?.getSource(OUTLINES) as GeoJSONSource | undefined)?.setData(featureCollection(outlines));
  }, [ready, outlines]);

  // The review layers follow the props; off, both sources are emptied and any popup closed
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource(REVIEW_KOMMUNER) as GeoJSONSource | undefined)?.setData(withGeometry(review?.coverage ?? null));
    (map.getSource(REVIEW_PLANS) as GeoJSONSource | undefined)?.setData(review?.plans ?? EMPTY);
    // A kommun's fill under the plans would tint their match colours: zoomed in, only its outline stays
    map.setLayoutProperty(`${REVIEW_KOMMUNER}-fill`, 'visibility', review?.plans ? 'none' : 'visible');
    if (!review) popupRef.current?.remove();
  }, [ready, review]);

  return <div ref={container} className="h-full w-full" aria-label={t('place.mapOfPilot')} />;
}
