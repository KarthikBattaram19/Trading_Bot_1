"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Overview" },
  { href: "/recommendations", label: "Recommendations" },
  { href: "/learning", label: "Learning" },
  { href: "/decisions", label: "Decisions" },
  { href: "/positions", label: "Positions" },
  { href: "/risk", label: "Risk" },
  { href: "/chat", label: "AI Chat" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen bg-surface text-gray-100">
      <aside className="flex w-56 shrink-0 flex-col border-r border-surface-border bg-surface-raised">
        <div className="border-b border-surface-border px-4 py-5">
          <h1 className="text-sm font-semibold tracking-wide text-white">
            Bhale Bullodu 1.0
          </h1>
          <p className="mt-1 text-xs text-gray-500">Voltality Trading Bot</p>
        </div>
        <nav className="flex flex-1 flex-col gap-1 p-3">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "rounded px-3 py-2 text-sm transition-colors",
                pathname === item.href || pathname.startsWith(item.href + "/")
                  ? "bg-accent-muted text-accent"
                  : "text-gray-400 hover:bg-surface-border hover:text-white"
              )}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="border-t border-surface-border p-3 text-xs text-gray-600">
          Docs/UI_Dashboard.md
        </div>
      </aside>
      <main className="flex flex-1 flex-col overflow-auto">{children}</main>
    </div>
  );
}
