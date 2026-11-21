import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import type { NavLinkRenderProps } from "react-router-dom";
import {
  Bookmark,
  BrainCircuit,
  CarFront,
  ClipboardCheck,
  Columns3,
  LayoutDashboard,
  LogOut,
  Menu,
  ScrollText,
  SlidersHorizontal,
  UserRound,
  Wallet,
  Warehouse,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { cn } from "../ui/cn";
import { Brand } from "./Brand";

// Persistent nav shell for every authenticated page - a React Router v7
// layout route (see App.tsx) rendering matched child routes via <Outlet />.
// /login and /register stay outside this tree entirely, so a logged-out
// user never sees nav chrome.
//
// One layout for buyers and admins: from lg (1024 px) a fixed navy sidebar
// (240 px) on the left with the buyer links, then - for an admin only - an
// "Admin" group, and the signed-in label and Logout pinned at the bottom;
// below lg a slim white top bar with a Menu button that opens the same
// links as a full-width drawer.

const NAV_LINKS: { to: string; label: string; icon: LucideIcon; end?: boolean; adminOnly?: boolean }[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/catalog", label: "Browse Catalog", icon: CarFront },
  { to: "/arena", label: "Compare Cars", icon: Columns3 },
  { to: "/scenarios", label: "My Comparisons", icon: Bookmark },
  { to: "/admin/ml-model-history", label: "ML Model Management", icon: BrainCircuit, adminOnly: true },
  { to: "/admin/fleet", label: "Fleet Management", icon: Warehouse, adminOnly: true },
  { to: "/admin/policy", label: "Policy Configuration", icon: SlidersHorizontal, adminOnly: true },
  { to: "/admin/vehicle-readiness", label: "Vehicle Readiness", icon: ClipboardCheck, adminOnly: true },
  { to: "/admin/audit-log", label: "Audit Log", icon: ScrollText, adminOnly: true },
  // end: "/profile/financial" starts with "/profile", so without it both entries were
  // highlighted on the Financial Profile page.
  { to: "/profile", label: "Profile", icon: UserRound, end: true },
  { to: "/profile/financial", label: "Financial Profile", icon: Wallet },
];

// The one breakpoint, for both roles: the sidebar from lg up, the Menu
// button and drawer below it. Class names are written out in full so
// Tailwind generates them.
export const NAV_BREAKPOINT = {
  sidebar: "lg:flex",
  menu: "lg:hidden",
  content: "lg:pl-60",
} as const;

// whitespace-nowrap: a label never breaks inside itself. Exactly one link is
// active per page (aria-current="page" from NavLink, plus the `end` rules above).
function navLinkClassName({ isActive }: NavLinkRenderProps): string {
  return cn(
    "flex items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-2 text-small transition-colors",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300",
    isActive
      ? "bg-side-active-bg font-semibold text-side-active"
      : "font-medium text-side-ink hover:bg-side-active-bg/60 hover:text-side-active",
  );
}

const sideButtonClassName = cn(
  "inline-flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-small font-semibold text-side-ink",
  "transition-colors hover:bg-side-active-bg hover:text-side-active",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300",
);

interface NavGroupsProps {
  isAdmin: boolean;
  onNavigate?: () => void;
}

// The links in two groups: everyone's, then (admins only) the Admin group.
function NavGroups({ isAdmin, onNavigate }: NavGroupsProps) {
  const buyerLinks = NAV_LINKS.filter((link) => !link.adminOnly);
  const adminLinks = NAV_LINKS.filter((link) => link.adminOnly);
  const renderLink = (link: (typeof NAV_LINKS)[number]) => {
    const Icon = link.icon;
    return (
      <NavLink key={link.to} to={link.to} end={link.end} className={navLinkClassName} onClick={onNavigate}>
        <Icon className="h-[17px] w-[17px] shrink-0" aria-hidden="true" />
        {link.label}
      </NavLink>
    );
  };
  return (
    <>
      <div className="flex flex-col gap-0.5">{buyerLinks.map(renderLink)}</div>
      {isAdmin && (
        <div className="mt-4 flex flex-col gap-0.5" data-nav-group="admin">
          <p className="px-3 pb-1 text-[0.6875rem] font-semibold uppercase tracking-[0.07em] text-side-label">Admin</p>
          {adminLinks.map(renderLink)}
        </div>
      )}
    </>
  );
}

export function AppShell() {
  const { user, logout } = useAuth();
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  // UC002: logout requires a YES/NO confirmation step before the session
  // actually ends - the sidebar and drawer Logout buttons both open the one
  // shared <ConfirmDialog> below.
  const [isLogoutConfirmOpen, setIsLogoutConfirmOpen] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  async function handleConfirmLogout() {
    setIsLoggingOut(true);
    try {
      await logout();
    } finally {
      setIsLoggingOut(false);
      setIsLogoutConfirmOpen(false);
    }
  }

  // FX-2 (item 2): Escape closes the phone Menu drawer and gives focus back to
  // the Menu button (not while the Logout dialog is open - Escape closes that).
  useEffect(() => {
    if (!isMenuOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isLogoutConfirmOpen) {
        setIsMenuOpen(false);
        menuButtonRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [isMenuOpen, isLogoutConfirmOpen]);

  const userLabel = user?.first_name || user?.email;
  // Admin-only entries stay hidden for everyone else - the same admin gate the
  // backend/ProtectedRoute already enforce, not a new access-control decision.
  const isAdmin = user?.role === "admin";
  const logoutTitle = userLabel ? `Signed in as ${userLabel}` : undefined;

  return (
    <div className="min-h-screen bg-page-bg">
      {/* FX-2 (item 10): the first focusable element; visible only when focused.
          It moves focus to <main> itself (no URL hash change for the router). */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-control focus:bg-surface focus:px-4 focus:py-2 focus:text-small focus:font-semibold focus:text-primary-700 focus:shadow-card focus:outline-none focus:ring-2 focus:ring-primary-500"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main-content")?.focus();
        }}
      >
        Skip to content
      </a>
      {/* Sidebar, lg and up */}
      <aside
        className={cn("fixed inset-y-0 left-0 z-30 hidden w-60 flex-col bg-side px-3 py-4", NAV_BREAKPOINT.sidebar)}
        data-shell="sidebar"
      >
        <div className="px-2 pb-4">
          <Brand onDark />
        </div>
        <nav aria-label="Primary" className="min-h-0 flex-1 overflow-y-auto">
          <NavGroups isAdmin={isAdmin} />
        </nav>
        <div className="mt-3 border-t border-side-active-bg px-2 pt-3">
          <p className="text-[0.6875rem] font-semibold uppercase tracking-[0.07em] text-side-label">Signed in as</p>
          <div className="mt-1 flex items-center justify-between gap-2">
            <span className="min-w-0 truncate text-small font-medium text-side-active" title={userLabel}>
              {userLabel}
            </span>
            <button type="button" className={sideButtonClassName} title={logoutTitle} onClick={() => setIsLogoutConfirmOpen(true)}>
              <LogOut className="h-4 w-4" aria-hidden="true" />
              Logout
            </button>
          </div>
        </div>
      </aside>

      {/* Top bar and Menu drawer, below lg */}
      <header className={cn("sticky top-0 z-30 border-b border-border bg-surface", NAV_BREAKPOINT.menu)}>
        <div className="flex h-14 items-center justify-between gap-4 px-4">
          <Brand onDark={false} />
          <button
            ref={menuButtonRef}
            type="button"
            className={cn(
              "inline-flex shrink-0 items-center gap-1.5 rounded-control border border-border px-3 py-2 text-small font-semibold text-ink",
              "hover:bg-surface-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500",
            )}
            aria-expanded={isMenuOpen}
            aria-controls="mobile-nav"
            onClick={() => setIsMenuOpen((open) => !open)}
          >
            {isMenuOpen ? <X className="h-4 w-4" aria-hidden="true" /> : <Menu className="h-4 w-4" aria-hidden="true" />}
            Menu
          </button>
        </div>

        {isMenuOpen && (
          <nav
            id="mobile-nav"
            aria-label="Primary"
            className={cn(
              "absolute inset-x-0 top-full max-h-[calc(100dvh-3.5rem)] overflow-y-auto bg-side px-3 py-3 shadow-card",
              NAV_BREAKPOINT.menu,
            )}
          >
            <NavGroups isAdmin={isAdmin} onNavigate={() => setIsMenuOpen(false)} />
            <div className="mt-3 flex items-center justify-between gap-4 border-t border-side-active-bg px-2 pt-3">
              <span className="min-w-0 truncate text-small font-medium text-side-active" title={userLabel}>
                {userLabel}
              </span>
              <button type="button" className={sideButtonClassName} title={logoutTitle} onClick={() => setIsLogoutConfirmOpen(true)}>
                <LogOut className="h-4 w-4" aria-hidden="true" />
                Logout
              </button>
            </div>
          </nav>
        )}
      </header>

      <main id="main-content" tabIndex={-1} className={cn(NAV_BREAKPOINT.content, "focus:outline-none")}>
        <Outlet />
      </main>

      <ConfirmDialog
        isOpen={isLogoutConfirmOpen}
        title="Log out of FlexiDriveMy?"
        message="You'll need to sign in again to continue."
        confirmLabel="YES"
        cancelLabel="NO"
        isConfirming={isLoggingOut}
        onConfirm={() => void handleConfirmLogout()}
        onCancel={() => setIsLogoutConfirmOpen(false)}
      />
    </div>
  );
}
