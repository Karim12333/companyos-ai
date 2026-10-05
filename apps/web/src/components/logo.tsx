import { cn } from "@/lib/format";

export function Logo({ compact, className }: { compact?: boolean; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <svg viewBox="0 0 28 28" className="size-7" aria-hidden>
        <rect width="28" height="28" rx="7" fill="var(--ink)" />
        <path d="M8 9.5h12M8 14h7.5M8 18.5h12" stroke="var(--surface)" strokeWidth="2" strokeLinecap="round" />
        <circle cx="19.5" cy="14" r="1.6" fill="var(--accent)" />
      </svg>
      {!compact && <span className="text-[15px] font-semibold tracking-tight text-ink">CompanyOS</span>}
    </div>
  );
}
