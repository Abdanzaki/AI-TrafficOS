import React from "react";

export interface StatProps {
  label: string;
  value: string;
  helperText?: string;
  className?: string;
}

export const Stat: React.FC<StatProps> = ({
  label,
  value,
  helperText,
  className = "",
}) => {
  return (
    <div
      className={`p-5 rounded-[10px] bg-surface border border-line flex flex-col items-center sm:items-start text-center sm:text-left transition-colors hover:border-pine/30 ${className}`}
    >
      <div className="font-display text-3xl sm:text-4xl font-semibold text-text tracking-tight tnum">
        {value}
      </div>
      <div className="text-[11px] uppercase tracking-[0.14em] font-semibold text-pine mt-1.5">
        {label}
      </div>
      {helperText && (
        <div className="text-xs text-muted mt-2 leading-relaxed">
          {helperText}
        </div>
      )}
    </div>
  );
};
