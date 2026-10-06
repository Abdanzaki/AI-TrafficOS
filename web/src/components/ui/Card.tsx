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
      className={`rounded-[14px] bg-surface border border-white/10 shadow-lg shadow-black/20 ${
        interactive
          ? "transition-all duration-200 hover:border-accent/40 hover:shadow-accent/5 hover:-translate-y-0.5"
          : ""
      } ${className}`}
      {...props}
    >
      {children}
    </div>
  );
};
