"use client";

import React from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";

export interface DensityPoint {
  time: string;
  density: number;
  occupancy?: number | null;
  speed?: number | null;
}

export interface DensityLineChartProps {
  data: DensityPoint[];
  height?: number;
  className?: string;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{
    name: string;
    value: number;
    color: string;
  }>;
  label?: string;
}

const CustomTooltip: React.FC<CustomTooltipProps> = ({
  active,
  payload,
  label,
}) => {
  if (!active || !payload || !payload.length) return null;

  return (
    <div className="rounded-lg bg-surface/95 border border-white/10 p-2.5 shadow-xl backdrop-blur-md text-xs">
      <div className="font-mono text-muted mb-1">{label}</div>
      <div className="space-y-1">
        {payload.map((entry, idx) => (
          <div key={idx} className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-1.5 text-muted">
              <span
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: entry.color }}
              />
              {entry.name}:
            </span>
            <span className="font-mono font-medium text-text">
              {entry.name.includes("Speed")
                ? `${entry.value} km/h`
                : `${entry.value}%`}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};

export const DensityLineChart: React.FC<DensityLineChartProps> = ({
  data,
  height = 240,
  className = "",
}) => {
  if (!data || data.length === 0) {
    return (
      <div
        style={{ height }}
        className={`w-full flex items-center justify-center text-xs text-muted font-mono bg-ink/30 rounded-xl border border-white/5 ${className}`}
      >
        No density/occupancy observations recorded
      </div>
    );
  }

  return (
    <div style={{ height }} className={`w-full ${className}`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={data}
          margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="rgba(255, 255, 255, 0.05)"
            vertical={false}
          />
          <XAxis
            dataKey="time"
            stroke="#8B93B0"
            fontSize={11}
            tickLine={false}
            axisLine={{ stroke: "rgba(255, 255, 255, 0.1)" }}
          />
          <YAxis
            stroke="#8B93B0"
            fontSize={11}
            domain={[0, 100]}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `${v}%`}
          />
          <Tooltip content={<CustomTooltip />} />
          <Line
            type="monotone"
            dataKey="density"
            name="Congestion / Density"
            stroke="#FFB800"
            strokeWidth={2}
            dot={{ r: 2, fill: "#FFB800" }}
            activeDot={{ r: 4, stroke: "#FFB800" }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};
