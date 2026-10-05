import type { ReactNode } from "react";

import { Logo } from "@/components/logo";

export function AuthLayout({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <main className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <section className="hidden flex-col justify-between border-r border-border bg-surface px-12 py-10 lg:flex">
        <Logo />
        <div className="max-w-md">
          <p className="text-[28px] leading-tight font-semibold tracking-tight text-ink">
            Run a company. Lead AI teams. Approve what matters.
          </p>
          <ul className="mt-8 space-y-4 text-sm text-ink-soft">
            {[
              ["Objectives, not prompts", "Give one business goal. Your Chief of Staff turns it into a plan."],
              ["Work that survives the night", "Durable execution keeps going after you close the browser."],
              ["You stay in control", "Publishing, emailing and spending always wait for your approval."],
            ].map(([title, body]) => (
              <li key={title} className="flex gap-3">
                <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-accent" aria-hidden />
                <span>
                  <span className="font-medium text-ink">{title}.</span> {body}
                </span>
              </li>
            ))}
          </ul>
        </div>
        <p className="text-xs text-faint">Multi-tenant · Audited · Human-approved external actions</p>
      </section>
      <section className="flex items-center justify-center px-5 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <Logo />
          </div>
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 mb-6 text-sm text-muted">{subtitle}</p>
          {children}
        </div>
      </section>
    </main>
  );
}
