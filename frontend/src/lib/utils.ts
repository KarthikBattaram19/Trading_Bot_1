import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** ₹ with Indian numbering (e.g. ₹1,00,000). Signed for P&L readability. */
export function formatCurrency(value: number, decimals = 0): string {
  const formatted = new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: decimals,
    minimumFractionDigits: decimals,
  }).format(Math.abs(value));
  return value < 0 ? `-${formatted}` : `${formatted}`;
}

export function formatPct(value: number, decimals = 1): string {
  return `${(value * 100).toFixed(decimals)}%`;
}

/** Stable IST datetime for SSR + client (avoids hydration locale mismatch). */
export function formatDateTime(value: string | number | Date): string {
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

/** Stable IST time-only for SSR + client. */
export function formatTime(value: string | number | Date): string {
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export function formatGreek(value: number, decimals = 2): string {
  if (Math.abs(value) >= 100) return value.toFixed(0);
  return value.toFixed(decimals);
}

export function remainingMs(expiresAt: string): number {
  return Math.max(0, new Date(expiresAt).getTime() - Date.now());
}

export function formatCountdown(expiresAt: string): string {
  const ms = remainingMs(expiresAt);
  const min = Math.floor(ms / 60000);
  const sec = Math.floor((ms % 60000) / 1000);
  return `${min}:${sec.toString().padStart(2, "0")}`;
}

/**
 * Mock UI data is opt-in for production.
 * - Explicit `true` / `false` always wins.
 * - If unset: mock only for local API (localhost / unset); remote API URLs use live data.
 *   This avoids Vercel staying on mock when NEXT_PUBLIC_API_URL points at Railway
 *   but NEXT_PUBLIC_USE_MOCK_DATA was left unset or not rebuilt as `"false"`.
 */
export function useMockData(): boolean {
  const flag = (process.env.NEXT_PUBLIC_USE_MOCK_DATA ?? "").trim().toLowerCase();
  if (flag === "true" || flag === "1") return true;
  if (flag === "false" || flag === "0") return false;

  const api = (process.env.NEXT_PUBLIC_API_URL ?? "").trim().toLowerCase();
  if (!api) return true;
  return (
    api.includes("localhost") ||
    api.includes("127.0.0.1") ||
    api.startsWith("http://0.0.0.0")
  );
}
