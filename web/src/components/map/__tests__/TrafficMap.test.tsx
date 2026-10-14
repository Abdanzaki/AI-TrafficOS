import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// Mock next/navigation
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
  }),
}));

const mockTileLayer = vi.fn();
const mockPolyline = vi.fn();

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: any) => (
    <div data-testid="map-container">{children}</div>
  ),
  TileLayer: (props: any) => {
    mockTileLayer(props);
    return (
      <div
        data-testid="tile-layer"
        data-url={props.url}
        data-zindex={props.zIndex}
        data-attribution={props.attribution}
      />
    );
  },
  Polyline: (props: any) => {
    mockPolyline(props);
    return (
      <div
        data-testid="polyline"
        data-color={props.pathOptions?.color}
        data-positions={JSON.stringify(props.positions)}
      />
    );
  },
  Marker: ({ children, title }: any) => (
    <div data-testid="marker" title={title}>
      {children}
    </div>
  ),
  Popup: ({ children }: any) => <div data-testid="popup">{children}</div>,
  useMap: () => ({
    setView: vi.fn(),
    fitBounds: vi.fn(),
  }),
}));

import {
  TrafficMap,
  getCorridorColor,
  getTomTomTileUrl,
  deriveCorridors,
  NEUTRAL_CORRIDOR_COLOR,
  type MappedJunction,
} from "../TrafficMap";

describe("TrafficMap Component", () => {
  const originalEnv = process.env.NEXT_PUBLIC_TOMTOM_API_KEY;

  beforeEach(() => {
    vi.clearAllMocks();
    delete process.env.NEXT_PUBLIC_TOMTOM_API_KEY;
  });

  afterEach(() => {
    if (originalEnv !== undefined) {
      process.env.NEXT_PUBLIC_TOMTOM_API_KEY = originalEnv;
    } else {
      delete process.env.NEXT_PUBLIC_TOMTOM_API_KEY;
    }
  });

  describe("Feature 1: Traffic Overlay Layer & Toggle", () => {
    it("hides toggle control and does not render TomTom layer when API key is absent", () => {
      process.env.NEXT_PUBLIC_TOMTOM_API_KEY = "";

      render(
        <TrafficMap
          junctions={[]}
          selectedId={null}
          onSelectJunction={vi.fn()}
        />
      );

      // Toggle UI must not be present
      expect(
        screen.queryByRole("switch", { name: /live traffic/i })
      ).not.toBeInTheDocument();
      expect(screen.queryByText("Live traffic")).not.toBeInTheDocument();

      // LIVE badge must not be present
      expect(screen.queryByText("LIVE")).not.toBeInTheDocument();

      // Legend honestly labels junction colors as system data
      expect(
        screen.getByText("Junction congestion (system data)")
      ).toBeInTheDocument();

      // Only base CARTO tile layer should be rendered
      expect(mockTileLayer).toHaveBeenCalledTimes(1);
      const calledUrl = mockTileLayer.mock.calls[0][0].url;
      expect(calledUrl).toContain("arcgisonline.com");
      expect(calledUrl).not.toContain("tomtom.com");
    });

    it("renders layer URL containing the key when key is set and overlay is active", () => {
      const testKey = "test_tomtom_api_key_abc123";
      process.env.NEXT_PUBLIC_TOMTOM_API_KEY = testKey;

      render(
        <TrafficMap
          junctions={[]}
          selectedId={null}
          onSelectJunction={vi.fn()}
          defaultLiveTraffic={true}
        />
      );

      // Toggle should exist and be checked
      const toggle = screen.getByRole("switch", { name: /live traffic/i });
      expect(toggle).toBeInTheDocument();
      expect(toggle).toHaveAttribute("aria-checked", "true");

      // LIVE badge and TomTom attribution text should exist
      expect(screen.getByText("LIVE")).toBeInTheDocument();
      expect(screen.getByText("(TomTom flow data)")).toBeInTheDocument();

      // Two TileLayers: base CARTO + TomTom flow
      expect(mockTileLayer).toHaveBeenCalledTimes(2);

      const tomtomCall = mockTileLayer.mock.calls.find((call) =>
        call[0].url.includes("tomtom.com")
      );
      expect(tomtomCall).toBeDefined();
      expect(tomtomCall![0].url).toBe(
        `https://api.tomtom.com/traffic/map/4/tile/flow/absolute/{z}/{x}/{y}.png?key=${testKey}`
      );
      expect(tomtomCall![0].zIndex).toBe(20);
      expect(tomtomCall![0].attribution).toContain("TomTom");
    });

    it("verifies getTomTomTileUrl helper format", () => {
      const url = getTomTomTileUrl("demo_key");
      expect(url).toBe(
        "https://api.tomtom.com/traffic/map/4/tile/flow/absolute/{z}/{x}/{y}.png?key=demo_key"
      );
    });

    it("toggles the TomTom overlay layer on and off via user interaction", () => {
      process.env.NEXT_PUBLIC_TOMTOM_API_KEY = "my_valid_key";

      render(
        <TrafficMap
          junctions={[]}
          selectedId={null}
          onSelectJunction={vi.fn()}
          defaultLiveTraffic={false}
        />
      );

      const toggle = screen.getByRole("switch", { name: /live traffic/i });
      expect(toggle).toHaveAttribute("aria-checked", "false");
      expect(screen.queryByText("LIVE")).not.toBeInTheDocument();
      expect(
        screen.getByText("Junction congestion (system data)")
      ).toBeInTheDocument();
      expect(mockTileLayer).toHaveBeenCalledTimes(1);

      // Turn ON
      mockTileLayer.mockClear();
      fireEvent.click(toggle);

      expect(toggle).toHaveAttribute("aria-checked", "true");
      expect(screen.getByText("LIVE")).toBeInTheDocument();
      expect(
        screen.queryByText("Junction congestion (system data)")
      ).not.toBeInTheDocument();
      expect(screen.getByText("Congestion Legend")).toBeInTheDocument();

      const tomtomCall = mockTileLayer.mock.calls.find((call) =>
        call[0].url.includes("tomtom.com")
      );
      expect(tomtomCall).toBeDefined();
      expect(tomtomCall![0].url).toContain("my_valid_key");

      // Turn OFF
      mockTileLayer.mockClear();
      fireEvent.click(toggle);

      expect(toggle).toHaveAttribute("aria-checked", "false");
      expect(screen.queryByText("LIVE")).not.toBeInTheDocument();
      expect(
        screen.getByText("Junction congestion (system data)")
      ).toBeInTheDocument();

      const tomtomCallOff = mockTileLayer.mock.calls.find((call) =>
        call[0].url.includes("tomtom.com")
      );
      expect(tomtomCallOff).toBeUndefined();
    });
  });

  describe("Feature 2: Richer Road Detail & Derived Corridors", () => {
    it("correctly maps corridor polyline colors based on endpoint congestion averages", () => {
      // Low congestion (< 40%) -> #15803D
      expect(getCorridorColor(20, 30)).toBe("#15803D");
      expect(getCorridorColor(0, 39)).toBe("#15803D");

      // Moderate congestion (40% - 69%) -> #B45309
      expect(getCorridorColor(40, 60)).toBe("#B45309");
      expect(getCorridorColor(30, 60)).toBe("#B45309"); // avg 45

      // High congestion (>= 70%) -> #B91C1C
      expect(getCorridorColor(70, 80)).toBe("#B91C1C");
      expect(getCorridorColor(60, 90)).toBe("#B91C1C"); // avg 75

      // Fallback neutral #3B4763 when either endpoint is null, undefined, or NaN
      expect(getCorridorColor(null, 50)).toBe(NEUTRAL_CORRIDOR_COLOR);
      expect(getCorridorColor(50, null)).toBe(NEUTRAL_CORRIDOR_COLOR);
      expect(getCorridorColor(undefined, 80)).toBe(NEUTRAL_CORRIDOR_COLOR);
      expect(getCorridorColor(80, undefined)).toBe(NEUTRAL_CORRIDOR_COLOR);
      expect(getCorridorColor(NaN, 50)).toBe(NEUTRAL_CORRIDOR_COLOR);
      expect(getCorridorColor(50, NaN)).toBe(NEUTRAL_CORRIDOR_COLOR);
      expect(getCorridorColor(null, null)).toBe(NEUTRAL_CORRIDOR_COLOR);
    });

    it("derives corridors between nearby junctions (<= 0.02 deg) and dedupes pairs", () => {
      const junctions: MappedJunction[] = [
        {
          id: 1,
          name: "Junction 1",
          code: "J1",
          status: "active",
          lat: 28.6139,
          lon: 77.209,
          congestionLevel: 20,
        },
        {
          id: 2,
          name: "Junction 2",
          code: "J2",
          status: "active",
          lat: 28.6239, // distance = 0.01 deg <= 0.02 deg
          lon: 77.209,
          congestionLevel: 30,
        },
        {
          id: 3,
          name: "Junction 3 (Far)",
          code: "J3",
          status: "active",
          lat: 28.7, // distance > 0.02 deg
          lon: 77.209,
          congestionLevel: 90,
        },
      ];

      const corridors = deriveCorridors(junctions);
      // Only 1 corridor should be derived (between J1 and J2)
      expect(corridors).toHaveLength(1);
      expect(corridors[0].fromJunctionId).toBe(1);
      expect(corridors[0].toJunctionId).toBe(2);
      expect(corridors[0].color).toBe("#15803D");

      // Even if duplicated junction entries exist in the array, pair is deduped
      const duplicated = [...junctions, junctions[0]];
      expect(deriveCorridors(duplicated)).toHaveLength(1);
    });

    it("renders corridor polylines in the map and displays the corridor legend row", () => {
      const junctions: MappedJunction[] = [
        {
          id: 10,
          name: "Junction A",
          code: "JA",
          status: "active",
          lat: 28.61,
          lon: 77.2,
          congestionLevel: 80,
        },
        {
          id: 20,
          name: "Junction B",
          code: "JB",
          status: "active",
          lat: 28.62,
          lon: 77.2,
          congestionLevel: 90,
        },
      ];

      render(
        <TrafficMap
          junctions={junctions}
          selectedId={null}
          onSelectJunction={vi.fn()}
        />
      );

      // Verify corridor row in legend
      expect(
        screen.getByText("Corridor (derived from junction network)")
      ).toBeInTheDocument();

      // Verify Polyline was called with high congestion color (#B91C1C)
      expect(mockPolyline).toHaveBeenCalledTimes(1);
      const polylineProps = mockPolyline.mock.calls[0][0];
      expect(polylineProps.pathOptions.color).toBe("#B91C1C");
      expect(polylineProps.positions).toEqual([
        [28.61, 77.2],
        [28.62, 77.2],
      ]);
    });
  });

  describe("Robustness: Junctions without valid coordinates", () => {
    it("does not crash on junctions without coords or with invalid coords", () => {
      const brokenJunctions: any[] = [
        {
          id: 1,
          name: "Missing Lat",
          code: "M1",
          status: "active",
          lon: 77.209,
        },
        {
          id: 2,
          name: "Missing Lon",
          code: "M2",
          status: "active",
          lat: 28.6139,
        },
        {
          id: 3,
          name: "NaN Coords",
          code: "M3",
          status: "active",
          lat: NaN,
          lon: NaN,
        },
        {
          id: 4,
          name: "Null Coords",
          code: "M4",
          status: "active",
          lat: null,
          lon: null,
        },
        {
          id: 5,
          name: "Valid Junction",
          code: "V1",
          status: "active",
          lat: 28.6139,
          lon: 77.209,
          congestionLevel: 45,
        },
      ];

      expect(() => {
        const corridors = deriveCorridors(brokenJunctions);
        expect(corridors).toEqual([]);
      }).not.toThrow();

      expect(() => {
        render(
          <TrafficMap
            junctions={brokenJunctions}
            selectedId={1}
            onSelectJunction={vi.fn()}
          />
        );
      }).not.toThrow();

      // Only the 1 valid junction marker should be rendered
      const markers = screen.getAllByTestId("marker");
      expect(markers).toHaveLength(1);
      expect(markers[0]).toHaveAttribute("title", expect.stringContaining("Valid Junction"));
    });
  });
});
