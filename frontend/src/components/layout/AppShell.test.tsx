import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./AppShell";
import { useAuth } from "../../context/AuthContext";

vi.mock("../../context/AuthContext", () => ({
  useAuth: vi.fn(),
}));

const mockedUseAuth = vi.mocked(useAuth);

function renderShell(initialPath = "/") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<div>Dashboard content</div>} />
          <Route path="/catalog" element={<div>Catalog content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AppShell", () => {
  const logout = vi.fn();

  beforeEach(() => {
    logout.mockReset();
    mockedUseAuth.mockReturnValue({
      user: {
        id: 1,
        email: "rider@example.com",
        first_name: "Alex",
        last_name: "Tan",
        phone_number: "",
        role: "user",
        date_joined: "2026-01-01",
      },
      isAuthenticated: true,
      isLoading: false,
      error: null,
      login: vi.fn(),
      logout,
      updateProfile: vi.fn(),
    });
  });

  it("renders all nav links and the signed-in user's name", () => {
    renderShell();

    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Browse Catalog" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "My Comparisons" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Profile" })).toBeInTheDocument();
    expect(screen.getByText("Alex")).toBeInTheDocument();
  });

  it("renders the matched child route via Outlet", () => {
    renderShell("/catalog");

    expect(screen.getByText("Catalog content")).toBeInTheDocument();
  });

  it("highlights the active nav link for the current route", () => {
    renderShell("/catalog");

    expect(screen.getByRole("link", { name: "Browse Catalog" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Browse Catalog" })).toHaveClass("bg-side-active-bg");
    expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveClass("bg-side-active-bg");
  });

  it("opens a confirmation dialog on Logout without calling logout() yet", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: "Logout" }));

    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(logout).not.toHaveBeenCalled();
  });

  it("leaves the session untouched when NO is clicked", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: "Logout" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "NO" }));

    expect(logout).not.toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("calls logout() and closes the dialog when YES is clicked", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(screen.getByRole("button", { name: "Logout" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "YES" }));

    expect(logout).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("routes both the desktop and mobile Logout buttons to the same shared dialog", async () => {
    const user = userEvent.setup();
    renderShell();

    // Open the mobile nav, then use ITS Logout button.
    await user.click(screen.getByRole("button", { name: "Menu" }));
    const mobileLogoutButtons = screen.getAllByRole("button", { name: "Logout" });
    await user.click(mobileLogoutButtons[mobileLogoutButtons.length - 1]);

    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "YES" }));

    expect(logout).toHaveBeenCalledTimes(1);
  });
});

describe("AppShell (FX-2)", () => {
  beforeEach(() => {
    mockedUseAuth.mockReturnValue({
      user: { id: 1, email: "rider@example.com", first_name: "Alex", last_name: "Tan", phone_number: "", role: "user", date_joined: "2026-01-01" },
      isAuthenticated: true,
      isLoading: false,
      error: null,
      login: vi.fn(),
      logout: vi.fn(),
      updateProfile: vi.fn(),
    });
  });

  // item 2
  it("Escape closes the phone Menu drawer and gives focus back to the Menu button", async () => {
    const user = userEvent.setup();
    renderShell();

    const menu = screen.getByRole("button", { name: "Menu" });
    await user.click(menu);
    expect(document.getElementById("mobile-nav")).toBeInTheDocument();
    await user.keyboard("{Escape}");

    expect(document.getElementById("mobile-nav")).not.toBeInTheDocument();
    expect(menu).toHaveFocus();
  });

  // item 10
  it("starts with a 'Skip to content' link that moves focus to the main content", async () => {
    const user = userEvent.setup();
    renderShell();

    await user.tab();
    const skip = screen.getByRole("link", { name: "Skip to content" });
    expect(skip).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(document.getElementById("main-content")).toHaveFocus();
    expect(screen.getByText("Dashboard content")).toBeInTheDocument();
  });
});
