import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./AppShell";
import { useAuth } from "../../context/AuthContext";

vi.mock("../../context/AuthContext", () => ({
  useAuth: vi.fn(),
}));

const mockedUseAuth = vi.mocked(useAuth);

// Run 2 fix batch 3: "/profile/financial" starts with "/profile", so the Profile entry
// used to light up as well. Exactly one nav entry is highlighted on each page.

function renderShell(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<div>Dashboard content</div>} />
          <Route path="/catalog" element={<div>Catalog content</div>} />
          <Route path="/catalog/:id/compare" element={<div>Compare content</div>} />
          <Route path="/profile" element={<div>Profile content</div>} />
          <Route path="/profile/financial" element={<div>Financial content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

function highlighted(): string[] {
  return screen
    .getAllByRole("link")
    .filter((link) => link.getAttribute("aria-current") === "page")
    .map((link) => link.textContent ?? "");
}

describe("AppShell active nav entry", () => {
  beforeEach(() => {
    mockedUseAuth.mockReturnValue({
      user: { id: 1, email: "a@b.com", first_name: "Alex", last_name: "", phone_number: "", role: "user", date_joined: "2026-01-01" },
      isAuthenticated: true,
      isLoading: false,
      error: null,
      login: vi.fn(),
      logout: vi.fn(),
      updateProfile: vi.fn(),
    });
  });

  it("highlights only 'Financial Profile' on /profile/financial", () => {
    renderShell("/profile/financial");

    expect(highlighted()).toEqual(["Financial Profile"]);
    expect(screen.getByRole("link", { name: "Profile" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "Profile" })).not.toHaveClass("bg-side-active-bg");
    expect(screen.getByRole("link", { name: "Financial Profile" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Financial Profile" })).toHaveClass("bg-side-active-bg");
  });

  it("highlights only 'Profile' on /profile", () => {
    renderShell("/profile");

    expect(highlighted()).toEqual(["Profile"]);
  });

  it("still highlights 'Browse Catalog' on a page below /catalog (its entry is not exact-match)", () => {
    renderShell("/catalog/5/compare");

    expect(highlighted()).toEqual(["Browse Catalog"]);
  });

  it("highlights only 'Dashboard' on /", () => {
    renderShell("/");

    expect(highlighted()).toEqual(["Dashboard"]);
  });
});
