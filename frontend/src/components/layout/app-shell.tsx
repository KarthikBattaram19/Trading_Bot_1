"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { Icon } from "@/components/ui/primitives";

const NAV = [
  { href: "/dashboard", label: "Overview", icon: "dashboard" },
  { href: "/recommendations", label: "Recommendations", icon: "auto_graph" },
  { href: "/learning", label: "Learning", icon: "school" },
  { href: "/decisions", label: "Decisions", icon: "psychology" },
  { href: "/positions", label: "Positions", icon: "format_list_bulleted" },
  { href: "/risk", label: "Risk", icon: "security" },
  { href: "/chat", label: "AI Chat", icon: "forum" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen bg-background text-on-background">
      <aside className="fixed left-0 top-0 z-50 flex h-full w-sidebar-width flex-col border-r border-outline-variant bg-surface-container">
        <div className="flex items-center gap-3 border-b border-outline-variant p-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full border border-outline-variant bg-surface-container-high">
            <Image
              src="/hanuman-emblem.png"
              alt="Sri Hanuman emblem"
              width={48}
              height={48}
              className="h-full w-full object-cover"
              priority
            />
          </div>
          <div className="min-w-0">
            <h2 className="truncate text-[16px] font-bold leading-tight text-on-surface">
              Bhale Bullodu 1.0
            </h2>
            <p className="truncate text-[12px] text-on-surface-variant">
              Volatility Trading Bot
            </p>
            <span className="font-mono text-[10px] text-outline">v1.0.0</span>
          </div>
        </div>

        <nav className="flex flex-1 flex-col gap-2 overflow-y-auto p-4">
          {NAV.map((item) => {
            const active =
              pathname === item.href || pathname.startsWith(item.href + "/");
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 rounded-md px-4 py-3 transition-colors duration-200",
                  active
                    ? "bg-secondary-container text-on-secondary-container"
                    : "text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface"
                )}
              >
                <Icon name={item.icon} className="text-[20px]" />
                <span className="text-label-caps uppercase">{item.label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-outline-variant p-4 text-[11px] text-outline">
          Paper-first · ICICI Direct + Market_News
        </div>
      </aside>

      <div className="ml-sidebar-width flex min-h-screen flex-1 flex-col">
        {children}
      </div>
    </div>
  );
}
