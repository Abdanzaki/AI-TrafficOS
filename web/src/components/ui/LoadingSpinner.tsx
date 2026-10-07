import React from "react";

export type SpinnerSize = "sm" | "md" | "lg" | "xl";

export interface LoadingSpinnerProps {
  size?: SpinnerSize;
  label?: string;
  className?: string;
  fullPage?: boolean;
}

const sizeMap: Record<SpinnerSize, string> = {
  sm: "w-4 h-4 border-2",
  md: "w-6 h-6 border-2",
  lg: "w-10 h-10 border-3",
  xl: "w-16 h-16 border-4",
};

export const LoadingSpinner: React.FC<LoadingSpinnerProps> = ({
  size = "md",
  label,
  className = "",
  fullPage = false,
}) => {
  const spinnerElement = (
    <div
      role="status"
      aria-label={label || "Loading"}
      className={`inline-flex flex-col items-center justify-center gap-3 ${className}`}
    >
      <div
        className={`${sizeMap[size]} rounded-full border-accent/20 border-t-accent animate-spin`}
      />
      {label && (
        <span className="text-xs sm:text-sm text-muted font-medium font-body animate-pulse">
          {label}
        </span>
      )}
      <span className="sr-only">{label || "Loading..."}</span>
    </div>
  );

  if (fullPage) {
    return (
      <div className="min-h-[50vh] w-full flex items-center justify-center p-8">
        {spinnerElement}
      </div>
    );
  }

  return spinnerElement;
};
