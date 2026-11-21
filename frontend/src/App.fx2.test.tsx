import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import { useAuth } from "./context/AuthContext";

// FX-2 (item 9, R4-F30f): an unknown address shows "Page not found"; a buyer on an admin address lands on the
// dashboard with a dismissible "That page is for administrators."; an admin on an unknown admin address gets the 404.
vi.mock("./context/AuthContext", () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => children,
  useAuth: vi.fn(),
}));
vi.mock("./api/scenarios", () => ({ listScenarios: vi.fn(() => Promise.resolve([])) }));
vi.mock("./api/catalog", () => ({ fetchEntireCatalog: vi.fn(() => Promise.resolve([])) }));
vi.mock("./api/mileageBands", () => ({ fetchMileageBands: vi.fn(() => Promise.resolve([])) }));

const mockedUseAuth = vi.mocked(useAuth);

function signedInAs(role: "user" | "admin") {
  mockedUseAuth.mockReturnValue({
    user: { id: 1, email: "x@example.com", first_name: "Alex", last_name: "Tan", phone_number: "", role, date_joined: "2026-01-01" },
    isAuthenticated: true,
    isLoading: false,
    error: null,
    login: vi.fn(),
    logout: vi.fn(),
    updateProfile: vi.fn(),
  });
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("App routes (FX-2)", () => {
  beforeEach(() => {
    mockedUseAuth.mockReset();
  });

  it("an unknown address shows 'Page not found' with the two ways out", async () => {
    signedInAs("user");
    renderAt("/comparisons");

    expect(await screen.findByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to dashboard" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Browse cars" })).toHaveAttribute("href", "/catalog");
  });

  it("a buyer on an admin address gets the dashboard with a notice that can be dismissed", async () => {
    signedInAs("user");
    const user = userEvent.setup();
    renderAt("/admin/fleet");

    expect(await screen.findByText("That page is for administrators.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: /Welcome back/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("That page is for administrators.")).not.toBeInTheDocument();
  });

  it("a buyer on an unknown admin address gets the same notice", async () => {
    signedInAs("user");
    renderAt("/admin/ml");

    expect(await screen.findByText("That page is for administrators.")).toBeInTheDocument();
  });

  it("an admin on an unknown admin address gets 'Page not found'", async () => {
    signedInAs("admin");
    renderAt("/admin/ml");

    expect(await screen.findByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
  });

  it("a signed-out visitor on an unknown address still goes to sign-in first", async () => {
    mockedUseAuth.mockReturnValue({
      user: null, isAuthenticated: false, isLoading: false, error: null, login: vi.fn(), logout: vi.fn(), updateProfile: vi.fn(),
    });
    renderAt("/comparisons");

    expect(await screen.findByRole("heading", { level: 1, name: /Sign in/ })).toBeInTheDocument();
  });
});
