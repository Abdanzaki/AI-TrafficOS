import React from "react";

export type BadgeVariant = "signal" | "pine" | "amber" | "muted" | "danger" | "success";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  children: React.ReactNode;
  className?: string;
  dot?: boolean;
}

const variantStyles: Record<BadgeVariant, { container: string; dot: string }> = {
  signal: {
    container: "bg-accent-tint text-accent-deep border-accent/30",
    dot: "bg-accent",
  },
  pine: {
    container: "bg-pine-tint text-pine-deep border-pine/25",
    dot: "bg-pine",
  },
  amber: {
    container: "bg-amber/10 text-amber border-amber/30",
    dot: "bg-amber",
  },
  muted: {
    container: "bg-ink/5 text-muted border-line",
    dot: "bg-faint",
  },
  danger: {
    container: "bg-danger/10 text-danger border-danger/30",
    dot: "bg-danger",
  },
  success: {
    container: "bg-success/10 text-success border-success/30",
    dot: "bg-success",
  },
};

export const Badge: React.FC<BadgeProps> = ({
  variant = "signal",
  children,
  className = "",
  dot = false,
  ...props
}) => {
  const styles = variantStyles[variant];

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-[11px] font-semibold border tracking-wide uppercase font-body select-none ${styles.container} ${className}`}
      {...props}
    >
      {dot && <span className={`w-1.5 h-1.5 rounded-full ${styles.dot}`} />}
      {children}
    </span>
  );
};
