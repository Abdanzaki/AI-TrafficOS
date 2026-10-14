import React from "react";

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  className?: string;
  interactive?: boolean;
}

export const Card: React.FC<CardProps> = ({
  children,
  className = "",
  interactive = false,
  ...props
}) => {
  return (
    <div
      className={`rounded-[10px] bg-surface border border-line shadow-[0_1px_2px_rgba(28,25,23,0.06)] ${
        interactive
          ? "transition-all duration-200 hover:border-pine/30 hover:shadow-[0_4px_12px_rgba(20,83,45,0.08)] hover:-translate-y-0.5"
          : ""
      } ${className}`}
      {...props}
    >
      {children}
    </div>
  );
};
