import React from "react";

export interface SectionHeadingProps {
  eyebrow?: string;
  title: string;
  description?: string;
  align?: "left" | "center";
  className?: string;
}

export const SectionHeading: React.FC<SectionHeadingProps> = ({
  eyebrow,
  title,
  description,
  align = "center",
  className = "",
}) => {
  const alignmentClass = align === "center" ? "text-center mx-auto" : "text-left";

  return (
    <div className={`max-w-3xl ${alignmentClass} ${className}`}>
      {eyebrow && (
        <span className="inline-block text-xs uppercase tracking-wider font-semibold text-accent mb-2">
          {eyebrow}
        </span>
      )}
      <h2 className="text-2xl sm:text-3xl lg:text-4xl font-bold font-display text-text tracking-tight">
        {title}
      </h2>
      {description && (
        <p className="mt-3 text-sm sm:text-base text-muted leading-relaxed">
          {description}
        </p>
      )}
    </div>
  );
};
