import type { ReactNode } from "react";
import { cn } from "./cn";

// The top of a page: an optional breadcrumb/back link, the page title (the
// page's one h1, in the display face), an optional one-line subtitle, and
// optional actions on the right. At 390 px the actions wrap below the title.
//
// Usage: <PageHeader title="Your financing options" subtitle="BMW 3 Series 320i Sport"
//                    breadcrumb={<Link to="/catalog">Browse Catalog</Link>}
//                    actions={<Button variant="secondary">Save</Button>} />

interface PageHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  breadcrumb?: ReactNode;
  actions?: ReactNode;
  className?: string;
}

export function PageHeader({ title, subtitle, breadcrumb, actions, className }: PageHeaderProps) {
  return (
    <header className={cn("flex flex-col gap-1", className)}>
      {breadcrumb && <div className="text-small text-ink-muted">{breadcrumb}</div>}
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          <h1 className="text-[1.625rem] font-bold leading-tight text-ink sm:text-[1.875rem]">{title}</h1>
          {subtitle && <p className="mt-1 text-small text-ink-muted">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}
