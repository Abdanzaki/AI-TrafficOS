"use client";

import React, { useId } from "react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";

export interface AreaTrafficPoint {
  time: string;
  vehicles: number;
  speed?: number | null;
  congestion?: number | null;
}

export interface AreaTrafficChartProps {
  data: AreaTrafficPoint[];
  height?: number;
  className?: string;
  showCongestion?: boolean;
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
    <div className="rounded-lg bg-surface/95 border border-white/10 p-3 shadow-xl backdrop-blur-md text-xs">
      <div className="font-mono text-muted mb-1.5">{label}</div>
      <div className="space-y-1">
        {payload.map((entry, idx) => (
          <div key={idx} className="flex items-center justify-between gap-4">
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
                : entry.name.includes("Congestion")
                ? `${entry.value}%`
                : entry.value.toLocaleString()}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};

export const AreaTrafficChart: React.FC<AreaTrafficChartProps> = ({
  data,
  height = 260,
  className = "",
  showCongestion = true,
}) => {
  const chartId = useId();
  const vehiclesGradId = `vehiclesGradient-${chartId.replace(/:/g, "")}`;
  const congestionGradId = `congestionGradient-${chartId.replace(/:/g, "")}`;

  if (!data || data.length === 0) {
    return (
      <div
        style={{ height }}
        className={`w-full flex items-center justify-center text-xs text-muted font-mono bg-ink/30 rounded-xl border border-white/5 ${className}`}
      >
        No telemetry observations in this window
      </div>
    );
  }

  return (
    <div style={{ height }} className={`w-full ${className}`}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={data}
          margin={{ top: 10, right: 25, left: 10, bottom: 0 }}
        >
          <defs>
            <linearGradient id={vehiclesGradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#00D9A8" stopOpacity={0.4} />
              <stop offset="95%" stopColor="#00D9A8" stopOpacity={0.0} />
            </linearGradient>
            <linearGradient id={congestionGradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#FFB800" stopOpacity={0.4} />
              <stop offset="95%" stopColor="#FFB800" stopOpacity={0.0} />
            </linearGradient>
          </defs>
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
            yAxisId="vehicles"
            stroke="#00D9A8"
            fontSize={11}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : `${v}`)}
          />
          {showCongestion && (
            <YAxis
              yAxisId="congestion"
              orientation="right"
              stroke="#FFB800"
              fontSize={11}
              domain={[0, 100]}
              unit="%"
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => `${v}%`}
            />
          )}
          <Tooltip content={<CustomTooltip />} />
          <Legend
            verticalAlign="top"
            height={32}
            iconType="circle"
            wrapperStyle={{
              fontSize: 12,
              paddingBottom: 4,
              color: "#8B93B0",
            }}
          />
          <Area
            yAxisId="vehicles"
            type="monotone"
            dataKey="vehicles"
            name="Vehicles"
            stroke="#00D9A8"
            strokeWidth={2}
            fillOpacity={1}
            fill={`url(#${vehiclesGradId})`}
          />
          {showCongestion && (
            <Area
              yAxisId="congestion"
              type="monotone"
              dataKey="congestion"
              name="Congestion"
              stroke="#FFB800"
              strokeWidth={1.5}
              fillOpacity={1}
              fill={`url(#${congestionGradId})`}
            />
          )}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
};
