import React from "react";
import { Inbox } from "lucide-react";
import { Button } from "./Button";

export interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick?: () => void;
    href?: string;
  };
  className?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  icon,
  title,
  description,
  action,
  className = "",
}) => {
  return (
    <div
      className={`p-8 sm:p-12 rounded-[14px] bg-surface/50 border border-white/10 text-center flex flex-col items-center justify-center max-w-lg mx-auto ${className}`}
    >
      <div className="w-14 h-14 rounded-2xl bg-surface/80 border border-white/10 flex items-center justify-center text-muted mb-4 shadow-inner">
        {icon || <Inbox className="w-7 h-7 text-muted/80" />}
      </div>

      <h3 className="font-display font-semibold text-lg text-text">
        {title}
      </h3>

      {description && (
        <p className="mt-2 text-sm text-muted max-w-md leading-relaxed">
          {description}
        </p>
      )}

      {action && (
        <div className="mt-6">
          <Button
            variant="primary"
            size="sm"
            href={action.href}
            onClick={action.onClick}
          >
            {action.label}
          </Button>
        </div>
      )}
    </div>
  );
};
