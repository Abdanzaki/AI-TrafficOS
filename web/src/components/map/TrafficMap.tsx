"use client";

import React, { useEffect, useMemo, useRef } from "react";
import { useRouter } from "next/navigation";
import "leaflet/dist/leaflet.css";
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import { CheckCircle2, AlertTriangle, AlertOctagon } from "lucide-react";
import { getCongestionStatus } from "@/lib/format";

export interface MappedJunction {
  id: number;
  name: string;
  code: string;
  status: string;
  city?: string | null;
  zone?: string | null;
  lat: number;
  lon: number;
  congestionLevel?: number | null;
  recordCount?: number;
}

export interface TrafficMapProps {
  junctions: MappedJunction[];
  selectedId: number | null;
  onSelectJunction: (id: number) => void;
  className?: string;
}

function createJunctionIcon(
  name: string,
  status: ReturnType<typeof getCongestionStatus>,
  isSelected: boolean
): L.DivIcon {
  const color = status.hex;
  const pulseClass = status.level === "high" ? "animate-ping" : "";

  const html = `
    <div
      role="button"
      tabindex="0"
      aria-label="${name}: ${status.label}"
      style="position: relative; width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; cursor: pointer; outline: none;"
    >
      ${
        isSelected || status.level === "high"
          ? `<div style="position: absolute; width: 32px; height: 32px; border-radius: 9999px; background-color: ${color}; opacity: 0.35; ${
              isSelected ? "" : pulseClass
            }"></div>`
          : ""
      }
      <div style="position: relative; width: ${isSelected ? "26px" : "20px"}; height: ${
    isSelected ? "26px" : "20px"
  }; border-radius: 9999px; background-color: #0B1020; border: 2.5px solid ${color}; display: flex; align-items: center; justify-content: center; box-shadow: 0 0 10px ${color}80; transition: all 0.2s;">
        <div style="width: ${isSelected ? "10px" : "7px"}; height: ${
    isSelected ? "10px" : "7px"
  }; border-radius: 9999px; background-color: ${color};"></div>
      </div>
    </div>
  `;

  return L.divIcon({
    html,
    className: "custom-junction-marker",
    iconSize: [36, 36],
    iconAnchor: [18, 18],
    popupAnchor: [0, -18],
  });
}

function MapBoundsFitter({
  markers,
  selectedLocation,
}: {
  markers: Array<[number, number]>;
  selectedLocation: [number, number] | null;
}) {
  const map = useMap();

  useEffect(() => {
    if (selectedLocation) {
      map.setView(selectedLocation, 16, { animate: true });
      return;
    }

    if (markers.length > 0) {
      if (markers.length === 1) {
        map.setView(markers[0], 14, { animate: true });
      } else {
        const bounds = L.latLngBounds(markers.map(([lat, lon]) => [lat, lon]));
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
      }
    }
  }, [map, markers, selectedLocation]);

  return null;
}

export const TrafficMap: React.FC<TrafficMapProps> = ({
  junctions,
  selectedId,
  onSelectJunction,
  className = "",
}) => {
  const validCoordinates = useMemo(() => {
    return junctions
      .filter((j) => typeof j.lat === "number" && typeof j.lon === "number" && !isNaN(j.lat) && !isNaN(j.lon))
      .map((j) => [j.lat, j.lon] as [number, number]);
  }, [junctions]);

  const selectedJunction = useMemo(() => {
    return junctions.find((j) => j.id === selectedId);
  }, [junctions, selectedId]);

  const selectedLocation = useMemo<[number, number] | null>(() => {
    if (
      selectedJunction &&
      typeof selectedJunction.lat === "number" &&
      typeof selectedJunction.lon === "number" &&
      !isNaN(selectedJunction.lat) &&
      !isNaN(selectedJunction.lon)
    ) {
      return [selectedJunction.lat, selectedJunction.lon];
    }
    return null;
  }, [selectedJunction]);

  const router = useRouter();
  const iconCacheRef = useRef<Map<string, L.DivIcon>>(new Map());

  const initialCenter: [number, number] = validCoordinates.length > 0
    ? validCoordinates[0]
    : [28.6139, 77.2090]; // Fallback coordinates

  return (
    <div className={`relative w-full h-full rounded-2xl overflow-hidden border border-white/10 ${className}`}>
      <MapContainer
        center={initialCenter}
        zoom={13}
        scrollWheelZoom={true}
        style={{ width: "100%", height: "100%", backgroundColor: "#0B1020" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank" rel="noreferrer">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          className="map-tiles"
        />

        <MapBoundsFitter
          markers={validCoordinates}
          selectedLocation={selectedLocation}
        />

        {junctions.map((j) => {
          if (typeof j.lat !== "number" || typeof j.lon !== "number" || isNaN(j.lat) || isNaN(j.lon)) {
            return null;
          }

          const isSelected = j.id === selectedId;
          const congStatus = getCongestionStatus(j.congestionLevel);
          const cacheKey = `${j.id}_${congStatus.level}_${isSelected ? 1 : 0}`;
          let icon = iconCacheRef.current.get(cacheKey);
          if (!icon) {
            icon = createJunctionIcon(j.name, congStatus, isSelected);
            iconCacheRef.current.set(cacheKey, icon);
          }

          const markerA11yLabel = `${j.name} - ${congStatus.label} (${j.status})`;

          return (
            <Marker
              key={j.id}
              position={[j.lat, j.lon]}
              icon={icon}
              keyboard={true}
              title={markerA11yLabel}
              alt={markerA11yLabel}
              eventHandlers={{
                click: () => onSelectJunction(j.id),
                keydown: (e: any) => {
                  if (e.originalEvent?.key === "Enter" || e.originalEvent?.key === " ") {
                    e.target.openPopup();
                    onSelectJunction(j.id);
                  }
                },
                keypress: (e: any) => {
                  if (e.originalEvent?.key === "Enter" || e.originalEvent?.key === " ") {
                    e.target.openPopup();
                    onSelectJunction(j.id);
                  }
                },
              }}
            >
              <Popup className="custom-popup">
                <div className="p-1 min-w-[190px] text-xs font-sans">
                  <div className="font-semibold text-sm text-text font-display">
                    {j.name}
                  </div>
                  <div className="text-[11px] text-muted font-mono mt-0.5">
                    Code: {j.code}
                  </div>
                  <div className="mt-2 pt-2 border-t border-white/10 flex items-center justify-between">
                    <span className="text-muted">Congestion:</span>
                    <span className="font-mono font-medium flex items-center gap-1" style={{ color: congStatus.hex }}>
                      {congStatus.level === "low" && <CheckCircle2 className="w-3 h-3 text-accent shrink-0" aria-hidden="true" />}
                      {congStatus.level === "medium" && <AlertTriangle className="w-3 h-3 text-amber shrink-0" aria-hidden="true" />}
                      {congStatus.level === "high" && <AlertOctagon className="w-3 h-3 text-danger shrink-0" aria-hidden="true" />}
                      {typeof j.congestionLevel === "number" ? `${Math.round(j.congestionLevel)}%` : "N/A"} ({congStatus.label})
                    </span>
                  </div>
                  <div className="mt-1 flex items-center justify-between text-[11px]">
                    <span className="text-muted">Status:</span>
                    <span className="capitalize font-mono text-text">{j.status}</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      onSelectJunction(j.id);
                      router.push(`/signals?junction=${j.id}`);
                    }}
                    className="w-full mt-2.5 py-1 px-2 rounded-md bg-accent/20 hover:bg-accent/30 text-accent font-medium text-center transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  >
                    View Controller Details →
                  </button>
                </div>
              </Popup>
            </Marker>
          );
        })}
      </MapContainer>

      {/* Map Legend Overlay */}
      <div className="absolute bottom-4 left-4 z-[1000] bg-surface/90 backdrop-blur-md border border-white/10 p-3 rounded-xl shadow-xl text-xs space-y-2 pointer-events-auto">
        <div className="font-display font-medium text-text text-[11px] uppercase tracking-wider">
          Congestion Legend
        </div>
        <div className="space-y-1.5 font-mono text-[11px]">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-3.5 h-3.5 text-accent shrink-0" aria-hidden="true" />
            <span className="w-2 h-2 rounded-full bg-accent shrink-0" />
            <span className="text-text font-medium">● Smooth</span>
            <span className="text-muted">&lt; 40%</span>
          </div>
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-3.5 h-3.5 text-amber shrink-0" aria-hidden="true" />
            <span className="w-2 h-2 rounded-full bg-amber shrink-0" />
            <span className="text-text font-medium">▲ Moderate</span>
            <span className="text-muted">40 - 69%</span>
          </div>
          <div className="flex items-center gap-2">
            <AlertOctagon className="w-3.5 h-3.5 text-danger animate-pulse shrink-0" aria-hidden="true" />
            <span className="w-2 h-2 rounded-full bg-danger animate-pulse shrink-0" />
            <span className="text-text font-medium">■ Congested</span>
            <span className="text-muted">&ge; 70%</span>
          </div>
        </div>
      </div>
    </div>
  );
};
