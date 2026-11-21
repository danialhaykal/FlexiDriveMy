import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { RegisterPage } from "./RegisterPage";
import { useAuth } from "../context/AuthContext";

vi.mock("../context/AuthContext", () => ({
  useAuth: vi.fn(),
}));

const mockedUseAuth = vi.mocked(useAuth);

function authState(isAuthenticated: boolean) {
  return {
    user: isAuthenticated
      ? { id: 1, email: "a@b.com", first_name: "", last_name: "", phone_number: "", role: "user" as const, date_joined: "2026-01-01T00:00:00Z" }
      : null,
    isAuthenticated,
    isLoading: false,
    error: null,
    login: vi.fn(),
    logout: vi.fn(),
    updateProfile: vi.fn(),
  };
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/" element={<p>Dashboard</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RegisterPage", () => {
  it("redirects an already-signed-in user from /register to the dashboard, like /login", () => {
    mockedUseAuth.mockReturnValue(authState(true));

    renderAt("/register");

    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.queryByText("Create your account")).not.toBeInTheDocument();
  });

  it("still shows the form to someone who is signed out", () => {
    mockedUseAuth.mockReturnValue(authState(false));

    renderAt("/register");

    expect(screen.getByRole("heading", { name: "Create your account" })).toBeInTheDocument();
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();
  });
});
