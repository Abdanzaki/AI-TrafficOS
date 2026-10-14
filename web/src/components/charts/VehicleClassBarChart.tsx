"use client";

import React from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
} from "recharts";

export interface VehicleClassItem {
  name: string;
  count: number;
  color?: string;
}

export interface VehicleClassBarChartProps {
  data: VehicleClassItem[];
  height?: number;
  className?: string;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{
    name: string;
    value: number;
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
    <div className="rounded-lg bg-surface border border-line p-2.5 shadow-lg text-xs">
      <div className="font-medium text-text capitalize mb-1">{label}</div>
      <div className="flex items-center gap-2 text-muted">
        <span>Detected count:</span>
        <span className="font-mono font-semibold text-accent">
          {payload[0].value.toLocaleString()}
        </span>
      </div>
    </div>
  );
};

const DEFAULT_COLORS: Record<string, string> = {
  car: "#14532D",
  truck: "#B45309",
  bus: "#C2410C",
  motorcycle: "#6B6257",
  bicycle: "#15803D",
};

export const VehicleClassBarChart: React.FC<VehicleClassBarChartProps> = ({
  data,
  height = 240,
  className = "",
}) => {
  if (!data || data.length === 0 || data.every((d) => d.count === 0)) {
    return (
      <div
        style={{ height }}
        className={`w-full flex items-center justify-center text-xs text-muted font-mono bg-cream/60 rounded-xl border border-line ${className}`}
      >
        No vehicle classification events detected
      </div>
    );
  }

  return (
    <div style={{ height }} className={`w-full ${className}`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="rgba(28, 25, 23, 0.08)"
            vertical={false}
          />
          <XAxis
            dataKey="name"
            stroke="#6B6257"
            fontSize={11}
            tickLine={false}
            axisLine={{ stroke: "rgba(28, 25, 23, 0.2)" }}
            tickFormatter={(val) => val.charAt(0).toUpperCase() + val.slice(1)}
          />
          <YAxis
            stroke="#6B6257"
            fontSize={11}
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
          />
          <Tooltip content={<CustomTooltip />} />
          <Bar dataKey="count" radius={[6, 6, 0, 0]}>
            {data.map((entry, index) => {
              const color =
                entry.color ||
                DEFAULT_COLORS[entry.name.toLowerCase()] ||
                "#C2410C";
              return <Cell key={`cell-${index}`} fill={color} />;
            })}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};
