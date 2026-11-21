import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AppShell, NAV_BREAKPOINT } from "./AppShell";
import { useAuth } from "../../context/AuthContext";

vi.mock("../../context/AuthContext", () => ({
  useAuth: vi.fn(),
}));

const mockedUseAuth = vi.mocked(useAuth);

// The navigation (redesign UI-1): ONE breakpoint for buyers and admins. From lg
// (1024 px) a fixed navy sidebar shows every link - the buyer links, then an
// "Admin" group for an admin - with the signed-in label and Logout at the bottom;
// below lg a white top bar shows a Menu button that opens the same links as a
// drawer. (Real widths are measured in the browser; jsdom has no layout, so these
// check the classes that produce it.)

const EMAIL = "someone.with.a.long.address@example.com";
const BUYER_ORDER = ["Dashboard", "Browse Catalog", "Compare Cars", "My Comparisons", "Profile", "Financial Profile"];
const ADMIN_ORDER = ["ML Model Management", "Fleet Management", "Policy Configuration", "Vehicle Readiness", "Audit Log"];

function renderAs(role: "user" | "admin") {
  mockedUseAuth.mockReturnValue({
    user: { id: 1, email: EMAIL, first_name: "", last_name: "", phone_number: "", role, date_joined: "2026-01-01" },
    isAuthenticated: true,
    isLoading: false,
    error: null,
    login: vi.fn(),
    logout: vi.fn(),
    updateProfile: vi.fn(),
  });
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<div>Dashboard content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

function sidebar(): HTMLElement {
  return document.querySelector('[data-shell="sidebar"]') as HTMLElement;
}

function linkLabels(container: Element): string[] {
  return Array.from(container.querySelectorAll("a")).map((a) => a.textContent ?? "");
}

describe.each([
  { role: "user" as const, links: BUYER_ORDER, adminGroup: false },
  { role: "admin" as const, links: [...BUYER_ORDER, ...ADMIN_ORDER], adminGroup: true },
])("navigation for a $role", ({ role, links, adminGroup }) => {
  it("shows the sidebar only from lg up, for both roles alike", () => {
    renderAs(role);

    expect(NAV_BREAKPOINT).toEqual({ sidebar: "lg:flex", menu: "lg:hidden", content: "lg:pl-60" });
    expect(sidebar()).toHaveClass("hidden", "lg:flex", "fixed", "w-60", "bg-side");
    expect(sidebar().className).not.toMatch(/min-\[\d+px\]/);
    expect(screen.getByRole("main")).toHaveClass("lg:pl-60");
  });

  it(`lists ${links.length} links in the sidebar, buyer links first, each with an icon and one line`, () => {
    renderAs(role);
    const nav = within(sidebar()).getByRole("navigation", { name: "Primary" });

    expect(linkLabels(nav)).toEqual(links);
    nav.querySelectorAll("a").forEach((link) => {
      expect(link).toHaveClass("whitespace-nowrap", "text-small");
      expect(link.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    });
  });

  it(adminGroup ? "puts the admin links under an Admin label" : "shows no Admin group", () => {
    renderAs(role);
    const group = sidebar().querySelector('[data-nav-group="admin"]');

    if (adminGroup) {
      expect(group).not.toBeNull();
      expect(group?.querySelector("p")).toHaveTextContent("Admin");
      expect(linkLabels(group!)).toEqual(ADMIN_ORDER);
    } else {
      expect(group).toBeNull();
      expect(within(sidebar()).queryByText("Admin")).not.toBeInTheDocument();
    }
  });

  it("pins the truncated signed-in label and Logout at the bottom of the sidebar", () => {
    renderAs(role);
    const label = within(sidebar()).getByTitle(EMAIL);

    expect(label).toHaveClass("truncate");
    const logout = within(sidebar()).getByRole("button", { name: "Logout" });
    expect(logout).toHaveAttribute("title", `Signed in as ${EMAIL}`);
    expect(logout.parentElement).toBe(label.parentElement);
  });

  it("uses a Menu button below lg that opens every link, the signed-in label and Logout", async () => {
    const user = userEvent.setup();
    renderAs(role);
    const button = screen.getByRole("button", { name: "Menu" });

    expect(button.closest("header")).toHaveClass("lg:hidden");
    expect(button).toHaveAttribute("aria-expanded", "false");
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");

    const mobile = document.getElementById("mobile-nav")!;
    expect(mobile).toHaveAttribute("aria-label", "Primary");
    expect(mobile).toHaveClass("lg:hidden");
    expect(linkLabels(mobile)).toEqual(links);
    expect(mobile).toHaveTextContent(EMAIL);
    expect(within(mobile).getByRole("button", { name: "Logout" })).toBeInTheDocument();
  });

  it("closes the Menu drawer when a link is chosen", async () => {
    const user = userEvent.setup();
    renderAs(role);

    await user.click(screen.getByRole("button", { name: "Menu" }));
    await user.click(within(document.getElementById("mobile-nav")!).getByRole("link", { name: "Dashboard" }));

    expect(document.getElementById("mobile-nav")).toBeNull();
  });
});
