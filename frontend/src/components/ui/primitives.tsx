import { cn } from "@/lib/utils";

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
        "rounded-lg border border-surface-border bg-surface-raised",
        className
      )}
    >
      {children}
    </div>
  );
}

export function Badge({
  variant = "default",
  children,
  className,
}: {
  variant?: "default" | "pass" | "warn" | "fail" | "pending";
  children: React.ReactNode;
  className?: string;
}) {
  const variants = {
    default: "bg-surface-border text-gray-200",
    pass: "bg-status-pass/20 text-status-pass",
    warn: "bg-status-warn/20 text-status-warn",
    fail: "bg-status-fail/20 text-status-fail",
    pending: "bg-status-pending/20 text-status-pending",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-2 py-0.5 text-xs font-medium",
        variants[variant],
        className
      )}
    >
      {children}
    </span>
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
    default: "border border-surface-border bg-surface-raised hover:bg-surface-border",
    primary: "bg-accent text-white hover:bg-blue-600",
    danger: "border border-status-fail/50 text-status-fail hover:bg-status-fail/10",
    ghost: "text-gray-400 hover:text-white hover:bg-surface-border",
  };
  const sizes = {
    sm: "px-2 py-1 text-xs",
    md: "px-4 py-2 text-sm",
    lg: "px-6 py-3 text-base",
  };
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "rounded font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40",
        variants[variant],
        sizes[size],
        className
      )}
    >
      {children}
    </button>
  );
}
