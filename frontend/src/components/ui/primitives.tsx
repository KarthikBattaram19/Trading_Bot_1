import { cn } from "@/lib/utils";

/** Material Symbols icon (see layout.tsx for the font link). */
export function Icon({
  name,
  className,
  filled,
}: {
  name: string;
  className?: string;
  filled?: boolean;
}) {
  return (
    <span
      aria-hidden
      className={cn("material-symbols-outlined leading-none", className)}
      style={filled ? { fontVariationSettings: '"FILL" 1' } : undefined}
    >
      {name}
    </span>
  );
}

export function Card({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-md border border-outline-variant bg-surface",
        className
      )}
    >
      {children}
    </div>
  );
}

/** Section panel with an optional titled, bordered header row. */
export function Panel({
  title,
  action,
  className,
  bodyClassName,
  children,
}: {
  title?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className={cn(
        "overflow-hidden rounded-md border border-outline-variant bg-surface",
        className
      )}
    >
      {(title || action) && (
        <div className="flex items-center justify-between border-b border-outline-variant bg-surface-container-low px-4 py-3">
          {typeof title === "string" ? (
            <h3 className="text-[16px] font-semibold text-on-surface">{title}</h3>
          ) : (
            title
          )}
          {action}
        </div>
      )}
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

type PillTone = "success" | "warning" | "danger" | "info" | "neutral";

const PILL_CLASS: Record<PillTone, string> = {
  success: "status-pill-success",
  warning: "status-pill-warning",
  danger: "status-pill-danger",
  info: "status-pill-info",
  neutral: "status-pill-neutral",
};

export function StatusPill({
  tone = "neutral",
  className,
  children,
}: {
  tone?: PillTone;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span className={cn("status-pill", PILL_CLASS[tone], className)}>
      {children}
    </span>
  );
}

/**
 * Legacy Badge kept for un-migrated components. Maps the old variant names
 * onto the new tonal pills.
 */
export function Badge({
  variant = "default",
  children,
  className,
}: {
  variant?: "default" | "pass" | "warn" | "fail" | "pending" | "info";
  children: React.ReactNode;
  className?: string;
}) {
  const tone: PillTone =
    variant === "pass"
      ? "success"
      : variant === "warn" || variant === "pending"
        ? "warning"
        : variant === "fail"
          ? "danger"
          : variant === "info"
            ? "info"
            : "neutral";
  return (
    <StatusPill tone={tone} className={className}>
      {children}
    </StatusPill>
  );
}

/** KPI stat card — label-caps top, mono value, optional pill/change. */
export function StatCard({
  label,
  value,
  icon,
  pill,
  change,
  tone = "default",
  className,
}: {
  label: string;
  value: React.ReactNode;
  icon?: string;
  pill?: { tone: PillTone; text: string };
  change?: { text: string; positive?: boolean };
  tone?: "default" | "warning" | "danger" | "success";
  className?: string;
}) {
  const toneRing =
    tone === "warning"
      ? "border-tertiary/40 bg-tertiary-container/10"
      : tone === "danger"
        ? "border-error/40 bg-error-container/10"
        : tone === "success"
          ? "border-secondary/40 bg-secondary-container/10"
          : "border-outline-variant";
  const valueColor =
    tone === "warning"
      ? "text-tertiary"
      : tone === "danger"
        ? "text-error"
        : tone === "success"
          ? "text-secondary"
          : "text-on-surface";
  return (
    <div
      className={cn(
        "flex h-[120px] flex-col justify-between rounded-md border bg-surface p-4",
        toneRing,
        className
      )}
    >
      <div className="flex items-center justify-between">
        <span className="text-label-caps uppercase text-on-surface-variant">
          {label}
        </span>
        {icon && <Icon name={icon} className={cn("text-[18px]", valueColor)} />}
      </div>
      <div className="mt-2 flex items-end justify-between">
        <span className={cn("font-mono text-data-lg", valueColor)}>{value}</span>
        {pill && <StatusPill tone={pill.tone}>{pill.text}</StatusPill>}
        {change && (
          <span
            className={cn(
              "font-mono text-data-sm",
              change.positive ? "text-secondary" : "text-error"
            )}
          >
            {change.text}
          </span>
        )}
      </div>
    </div>
  );
}

export function Button({
  variant = "default",
  size = "md",
  className,
  disabled,
  onClick,
  children,
}: {
  variant?: "default" | "primary" | "danger" | "ghost";
  size?: "sm" | "md" | "lg";
  className?: string;
  disabled?: boolean;
  onClick?: () => void;
  children: React.ReactNode;
}) {
  const variants = {
    default:
      "border border-outline-variant bg-surface-container text-on-surface hover:bg-surface-container-high",
    primary:
      "bg-primary-container text-white hover:brightness-110",
    danger:
      "border border-error/50 text-error hover:bg-error/10",
    ghost: "text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface",
  };
  const sizes = {
    sm: "px-3 py-1.5 text-data-sm",
    md: "px-4 py-2 text-sm",
    lg: "px-6 py-3 text-base",
  };
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40",
        variants[variant],
        sizes[size],
        className
      )}
    >
      {children}
    </button>
  );
}
