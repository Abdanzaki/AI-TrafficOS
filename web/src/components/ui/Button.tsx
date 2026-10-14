import React from "react";
import Link from "next/link";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "terracotta";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  href?: string;
  external?: boolean;
  children: React.ReactNode;
  className?: string;
}

const variantStyles: Record<ButtonVariant, string> = {
  primary:
    "bg-pine text-paper font-semibold hover:bg-pine-deep active:scale-[0.98] shadow-sm border border-pine-deep/40",
  terracotta:
    "bg-accent text-paper font-semibold hover:bg-accent-deep active:scale-[0.98] shadow-sm border border-accent-deep/40",
  secondary:
    "bg-surface text-text font-medium border border-line hover:border-pine/40 hover:bg-cream/50 active:scale-[0.98]",
  ghost:
    "bg-transparent text-muted font-medium hover:text-text hover:bg-ink/5 active:scale-[0.98] border border-transparent",
};

const sizeStyles: Record<ButtonSize, string> = {
  sm: "text-xs px-3.5 py-1.5 gap-1.5",
  md: "text-sm px-5 py-2.5 gap-2",
  lg: "text-base px-6 py-3.5 gap-2.5",
};

export const Button: React.FC<ButtonProps> = ({
  variant = "primary",
  size = "md",
  href,
  external,
  children,
  className = "",
  disabled,
  ...props
}) => {
  const baseStyles =
    "inline-flex items-center justify-center rounded-lg transition-all duration-200 select-none cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-paper disabled:opacity-50 disabled:pointer-events-none disabled:cursor-not-allowed";

  const combinedStyles = `${baseStyles} ${variantStyles[variant]} ${sizeStyles[size]} ${className}`;

  if (href) {
    if (external) {
      return (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className={combinedStyles}
        >
          {children}
        </a>
      );
    }

    return (
      <Link href={href} className={combinedStyles}>
        {children}
      </Link>
    );
  }

  return (
    <button className={combinedStyles} disabled={disabled} {...props}>
      {children}
    </button>
  );
};
