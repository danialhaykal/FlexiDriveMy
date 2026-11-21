import type { ReactNode } from "react";
import { Bookmark, Calculator, ChartLine } from "lucide-react";
import { Brand } from "../layout/Brand";
import { Card } from "../ui/Card";

// The sign-in and register pages' frame. From lg a navy panel on the left
// says what the app does (no figures, no claims beyond it), the form on the
// right in a white card; below lg just the brand above the form.

const POINTS = [
  { icon: Calculator, text: "Monthly payments for each option, side by side" },
  { icon: ChartLine, text: "Total cost of ownership with a resale forecast" },
  { icon: Bookmark, text: "Save comparisons and export them as a PDF" },
];

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-page-bg lg:grid lg:grid-cols-2">
      <aside className="hidden flex-col justify-center bg-side px-12 py-16 lg:flex" data-auth-panel>
        <div className="mx-auto w-full max-w-md">
          <Brand onDark />
          <p className="mt-8 font-display text-[1.75rem] font-bold leading-tight text-white">
            Compare Hire Purchase, GFV and Subscription in one place.
          </p>
          <ul className="mt-8 flex flex-col gap-4">
            {POINTS.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-3 text-body text-side-ink">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-side-active-bg">
                  <Icon className="h-[18px] w-[18px] text-white" aria-hidden="true" />
                </span>
                {text}
              </li>
            ))}
          </ul>
        </div>
      </aside>

      <div className="flex flex-col items-center px-4 py-10 sm:py-16 lg:justify-center">
        <Brand onDark={false} className="mb-6 lg:hidden" />
        <div className="w-full max-w-sm">
          <Card>{children}</Card>
        </div>
      </div>
    </div>
  );
}
