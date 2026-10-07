import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Car } from "lucide-react";

describe("UI State Components", () => {
  describe("LoadingSpinner", () => {
    it("renders with default accessibility role and sr-only label", () => {
      render(<LoadingSpinner />);
      const statusElement = screen.getByRole("status");
      expect(statusElement).toBeInTheDocument();
      expect(statusElement).toHaveAttribute("aria-label", "Loading");
      expect(screen.getByText("Loading...")).toBeInTheDocument();
    });

    it("renders custom label when provided", () => {
      render(<LoadingSpinner label="Fetching telemetry data..." />);
      expect(screen.getByRole("status")).toHaveAttribute("aria-label", "Fetching telemetry data...");
      expect(screen.getAllByText("Fetching telemetry data...")).toHaveLength(2);
    });

    it("applies different sizes correctly", () => {
      const { container: smContainer } = render(<LoadingSpinner size="sm" />);
      expect(smContainer.querySelector(".w-4.h-4")).toBeInTheDocument();

      const { container: lgContainer } = render(<LoadingSpinner size="lg" />);
      expect(lgContainer.querySelector(".w-10.h-10")).toBeInTheDocument();

      const { container: xlContainer } = render(<LoadingSpinner size="xl" />);
      expect(xlContainer.querySelector(".w-16.h-16")).toBeInTheDocument();
    });

    it("renders within fullPage layout wrapper when fullPage is true", () => {
      const { container } = render(<LoadingSpinner fullPage label="Booting TrafficOS..." />);
      expect(container.querySelector(".min-h-\\[50vh\\]")).toBeInTheDocument();
      expect(screen.getAllByText("Booting TrafficOS...")).toHaveLength(2);
    });
  });

  describe("ErrorState", () => {
    it("renders error message and default title with role='alert'", () => {
      render(<ErrorState message="Network connection failed" />);
      const alert = screen.getByRole("alert");
      expect(alert).toBeInTheDocument();
      expect(screen.getByText("An error occurred")).toBeInTheDocument();
      expect(screen.getByText("Network connection failed")).toBeInTheDocument();
      expect(screen.queryByRole("button")).not.toBeInTheDocument();
    });

    it("renders custom title and retry button with callback", () => {
      const onRetryMock = vi.fn();
      render(
        <ErrorState
          title="Telemetry Feed Lost"
          message="Sensors at junction J-101 are unreachable"
          onRetry={onRetryMock}
          retryText="Reconnect Sensor"
        />
      );

      expect(screen.getByText("Telemetry Feed Lost")).toBeInTheDocument();
      expect(screen.getByText("Sensors at junction J-101 are unreachable")).toBeInTheDocument();

      const retryBtn = screen.getByRole("button", { name: /reconnect sensor/i });
      expect(retryBtn).toBeInTheDocument();

      fireEvent.click(retryBtn);
      expect(onRetryMock).toHaveBeenCalledTimes(1);
    });
  });

  describe("EmptyState", () => {
    it("renders title, description and default icon", () => {
      render(
        <EmptyState
          title="No Active Incidents"
          description="All traffic corridors are currently clear of collisions."
        />
      );

      expect(screen.getByText("No Active Incidents")).toBeInTheDocument();
      expect(
        screen.getByText("All traffic corridors are currently clear of collisions.")
      ).toBeInTheDocument();
      expect(screen.queryByRole("button")).not.toBeInTheDocument();
    });

    it("renders custom icon and action button with callback", () => {
      const onActionClick = vi.fn();
      render(
        <EmptyState
          icon={<Car data-testid="car-icon" className="w-8 h-8" />}
          title="No Vehicles Logged"
          description="Awaiting camera detections."
          action={{
            label: "Trigger Calibration",
            onClick: onActionClick,
          }}
        />
      );

      expect(screen.getByTestId("car-icon")).toBeInTheDocument();
      const actionBtn = screen.getByRole("button", { name: /trigger calibration/i });
      expect(actionBtn).toBeInTheDocument();

      fireEvent.click(actionBtn);
      expect(onActionClick).toHaveBeenCalledTimes(1);
    });

    it("renders action button as link when href is supplied", () => {
      render(
        <EmptyState
          title="No Intersections Found"
          action={{
            label: "Go to Dashboard",
            href: "/dashboard",
          }}
        />
      );

      const link = screen.getByRole("link", { name: /go to dashboard/i });
      expect(link).toBeInTheDocument();
      expect(link).toHaveAttribute("href", "/dashboard");
    });
  });
});
