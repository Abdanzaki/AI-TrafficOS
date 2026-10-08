import React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "./Button";

export interface PaginationProps {
  page: number;
  totalPages: number;
  totalRecords?: number;
  perPage?: number;
  onPageChange: (page: number) => void;
  recordLabel?: string;
  className?: string;
}

export const Pagination: React.FC<PaginationProps> = ({
  page,
  totalPages,
  totalRecords,
  perPage = 15,
  onPageChange,
  recordLabel = "records",
  className = "",
}) => {
  if (totalPages <= 0) return null;

  const from = totalRecords === 0 ? 0 : (page - 1) * perPage + 1;
  const to =
    totalRecords !== undefined
      ? Math.min(page * perPage, totalRecords)
      : page * perPage;

  return (
    <div
      className={`p-4 border-t border-white/5 bg-ink/30 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs ${className}`}
    >
      <div className="text-muted">
        {totalRecords !== undefined ? (
          <>
            Showing{" "}
            <span className="font-mono text-text font-medium">{from}</span> to{" "}
            <span className="font-mono text-text font-medium">{to}</span> of{" "}
            <span className="font-mono text-text font-medium">{totalRecords}</span>{" "}
            {recordLabel}
          </>
        ) : (
          <span>
            Page{" "}
            <span className="font-mono text-text font-medium">{page}</span> of{" "}
            <span className="font-mono text-text font-medium">
              {Math.max(1, totalPages)}
            </span>
          </span>
        )}
      </div>

      <div className="flex items-center gap-1.5">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => onPageChange(Math.max(1, page - 1))}
          disabled={page <= 1}
          className="gap-1 px-2.5 py-1"
          aria-label="Previous page"
        >
          <ChevronLeft className="w-3.5 h-3.5" />
          <span>Prev</span>
        </Button>

        <span className="px-3 py-1 font-mono text-text text-xs bg-ink/60 rounded-md border border-white/5">
          Page {page} of {Math.max(1, totalPages)}
        </span>

        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => onPageChange(Math.min(totalPages, page + 1))}
          disabled={page >= totalPages}
          className="gap-1 px-2.5 py-1"
          aria-label="Next page"
        >
          <span>Next</span>
          <ChevronRight className="w-3.5 h-3.5" />
        </Button>
      </div>
    </div>
  );
};
