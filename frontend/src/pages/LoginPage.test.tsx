import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { LoginPage } from "./LoginPage";
import { useAuth } from "../context/AuthContext";

vi.mock("../context/AuthContext", () => ({
  useAuth: vi.fn(),
}));

const mockedUseAuth = vi.mocked(useAuth);

function renderAt(path: string, state?: unknown) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: path, state }]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<p>Dashboard</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("LoginPage", () => {
  it("QA audit M20: shows a success banner right after registering", () => {
    mockedUseAuth.mockReturnValue({
      user: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,
      login: vi.fn(),
      logout: vi.fn(),
      updateProfile: vi.fn(),
    });

    renderAt("/login", { justRegistered: true });

    expect(screen.getByRole("status")).toHaveTextContent("Account created - please sign in.");
  });

  it("QA audit L15: redirects an already-authenticated user away from /login", () => {
    mockedUseAuth.mockReturnValue({
      user: { id: 1, email: "a@b.com", first_name: "", last_name: "", phone_number: "", role: "user", date_joined: "2026-01-01T00:00:00Z" },
      isAuthenticated: true,
      isLoading: false,
      error: null,
      login: vi.fn(),
      logout: vi.fn(),
      updateProfile: vi.fn(),
    });

    renderAt("/login");

    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.queryByText("Sign in to FlexiDriveMy")).not.toBeInTheDocument();
  });
});
