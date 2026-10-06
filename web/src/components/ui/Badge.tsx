import React from "react";

export type BadgeVariant = "teal" | "amber" | "muted" | "danger" | "success";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  children: React.ReactNode;
  className?: string;
  dot?: boolean;
}

const variantStyles: Record<BadgeVariant, { container: string; dot: string }> = {
  teal: {
    container: "bg-accent/10 text-accent border-accent/30",
    dot: "bg-accent",
  },
  amber: {
    container: "bg-amber/10 text-amber border-amber/30",
    dot: "bg-amber",
  },
  muted: {
    container: "bg-muted/10 text-muted border-muted/30",
    dot: "bg-muted",
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
  variant = "teal",
  children,
  className = "",
  dot = false,
  ...props
}) => {
  const styles = variantStyles[variant];

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border tracking-wide uppercase font-body select-none ${styles.container} ${className}`}
      {...props}
    >
      {dot && <span className={`w-1.5 h-1.5 rounded-full ${styles.dot}`} />}
      {children}
    </span>
  );
};
