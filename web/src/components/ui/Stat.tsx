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
      className={`p-5 rounded-[14px] bg-surface/60 border border-white/10 flex flex-col items-center sm:items-start text-center sm:text-left transition-colors hover:border-white/20 ${className}`}
    >
      <div className="font-display text-2xl sm:text-3xl font-bold text-text tracking-tight">
        {value}
      </div>
      <div className="text-xs uppercase tracking-wider font-semibold text-accent mt-1">
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
