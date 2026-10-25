'use client';

import 'maplibre-gl/dist/maplibre-gl.css';
import { useEffect, useRef, useState } from 'react';
import type { GeoJSONSource, Map as MapLibreMap, MapMouseEvent, Marker } from 'maplibre-gl';

import type { Pin } from '@/lib/place';

export interface PlaceOutline {
  id: string;
  kind: 'property' | 'plan' | 'zone';
  geometry: GeoJSON.Geometry;
}

export interface PlaceMapProps {
  pin: Pin | null;
  outlines: PlaceOutline[]; // drawn over the base map: the property, its plans and zones
  bounds?: [number, number, number, number] | null; // west, south, east, north: first view
  onMapClick: (pin: Pin) => void;
}

// OpenFreeMap: OpenStreetMap vector tiles, free and keyless; Positron is the light, quiet style
const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron';
const SWEDEN: [number, number, number, number] = [10.5, 55.0, 24.5, 69.5];
const OUTLINES = 'place-outlines';
const PIN_ZOOM = 16;
// Apple system colours: blue for the property, orange (dashed) for plans, green for land-use zones; one layer per
// kind, drawn zones first so the property's outline stays on top
const KIND_STYLE: { kind: PlaceOutline['kind']; color: string; fill: number; width: number; dash?: number[] }[] = [
  { kind: 'zone', color: '#30d158', fill: 0.06, width: 1 },
  { kind: 'plan', color: '#ff9f0a', fill: 0, width: 1.25, dash: [3, 2] },
  { kind: 'property', color: '#0a84ff', fill: 0.14, width: 2.5 },
];

function featureCollection(outlines: PlaceOutline[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: outlines.map((outline) => ({
      type: 'Feature', geometry: outline.geometry, properties: { id: outline.id, kind: outline.kind },
    })),
  };
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

/** The base map (MapLibre, OpenFreeMap tiles) with the pin and the outlines; a click reports the point. */
export default function PlaceMap({ pin, outlines, bounds, onMapClick }: PlaceMapProps) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markerRef = useRef<Marker | null>(null);
  const onClickRef = useRef(onMapClick);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    onClickRef.current = onMapClick;
  }, [onMapClick]);

  // One map for the component's life; MapLibre is loaded here so server rendering never imports it
  useEffect(() => {
    let cancelled = false;
    import('maplibre-gl').then((maplibregl) => {
      if (cancelled || !container.current) return;
      // MapLibre finds its worker next to its own file, which the bundler moved: emit it and point there
      maplibregl.setWorkerUrl(new URL('maplibre-gl/dist/maplibre-gl-worker.mjs', import.meta.url).toString());
      const map = new maplibregl.Map({
        container: container.current, style: STYLE_URL, bounds: SWEDEN, fitBoundsOptions: { padding: 24 },
        attributionControl: { compact: true }, dragRotate: false, pitchWithRotate: false,
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
      map.on('click', (event: MapMouseEvent) => onClickRef.current({ lat: event.lngLat.lat, lon: event.lngLat.lng }));
      map.on('load', () => {
        addOutlineLayers(map);
        setReady(true);
      });
      markerRef.current = new maplibregl.Marker({ color: '#ff375f' });
      mapRef.current = map;
    });
    return () => {
      cancelled = true;
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (ready && bounds && !pin) mapRef.current?.fitBounds(bounds, { padding: 24, duration: 0 });
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
    if (!ready) return;
    (mapRef.current?.getSource(OUTLINES) as GeoJSONSource | undefined)?.setData(featureCollection(outlines));
  }, [ready, outlines]);

  return <div ref={container} className="h-full w-full" aria-label="Map of the pilot kommuner" />;
}
