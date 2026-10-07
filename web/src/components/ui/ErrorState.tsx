import React from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "./Button";

export interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  retryText?: string;
  className?: string;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  title = "An error occurred",
  message,
  onRetry,
  retryText = "Try again",
  className = "",
}) => {
  return (
    <div
      role="alert"
      className={`p-6 sm:p-8 rounded-[14px] bg-surface/70 border border-danger/30 text-center flex flex-col items-center justify-center max-w-lg mx-auto ${className}`}
    >
      <div className="w-12 h-12 rounded-xl bg-danger/15 border border-danger/30 flex items-center justify-center text-danger mb-4 shadow-sm">
        <AlertTriangle className="w-6 h-6" />
      </div>

      <h3 className="font-display font-semibold text-lg text-text">
        {title}
      </h3>

      <p className="mt-2 text-sm text-muted max-w-md leading-relaxed">
        {message}
      </p>

      {onRetry && (
        <div className="mt-6">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={onRetry}
            className="border-danger/30 hover:border-danger/60 text-text"
          >
            <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
            {retryText}
          </Button>
        </div>
      )}
    </div>
  );
};
