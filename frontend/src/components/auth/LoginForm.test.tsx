import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginForm } from "./LoginForm";
import { useAuth } from "../../context/AuthContext";

vi.mock("../../context/AuthContext", () => ({
  useAuth: vi.fn(),
}));

const mockedUseAuth = vi.mocked(useAuth);

describe("LoginForm", () => {
  const login = vi.fn();

  beforeEach(() => {
    login.mockReset();
    mockedUseAuth.mockReturnValue({
      user: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,
      login,
      logout: vi.fn(),
      updateProfile: vi.fn(),
    });
  });

  it("renders email and password fields", () => {
    render(<LoginForm />);

    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("submits the entered credentials and calls onSuccess", async () => {
    login.mockResolvedValueOnce(undefined);
    const onSuccess = vi.fn();
    const user = userEvent.setup();

    render(<LoginForm onSuccess={onSuccess} />);

    await user.type(screen.getByLabelText(/email/i), "rider@example.com");
    await user.type(screen.getByLabelText(/password/i), "StrongPassw0rd!23");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() =>
      expect(login).toHaveBeenCalledWith("rider@example.com", "StrongPassw0rd!23"),
    );
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
  });

  it("shows the credentials-wrong message for a real 401", async () => {
    login.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 401, data: { detail: "No active account found with the given credentials" } },
    });
    const user = userEvent.setup();

    render(<LoginForm />);

    await user.type(screen.getByLabelText(/email/i), "rider@example.com");
    await user.type(screen.getByLabelText(/password/i), "wrong-password");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid email or password/i);
  });

  // --- Live-walkthrough finding (2026-10-05): a bare `catch` previously
  // showed "Invalid email or password." for ANY failure, including a
  // network outage or a 503 - misleading, since neither has anything to
  // do with the entered credentials.

  it("shows a server-unreachable message for a network error (no response at all)", async () => {
    login.mockRejectedValueOnce({ isAxiosError: true, response: undefined });
    const user = userEvent.setup();

    render(<LoginForm />);

    await user.type(screen.getByLabelText(/email/i), "rider@example.com");
    await user.type(screen.getByLabelText(/password/i), "StrongPassw0rd!23");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not reach the server/i);
  });

  it("shows a generic message for a non-401 server error (e.g. a 503)", async () => {
    login.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 503, data: { detail: "Service unavailable" } },
    });
    const user = userEvent.setup();

    render(<LoginForm />);

    await user.type(screen.getByLabelText(/email/i), "rider@example.com");
    await user.type(screen.getByLabelText(/password/i), "StrongPassw0rd!23");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/something went wrong/i);
  });

  it("shows the generic message for a non-axios error, never claiming bad credentials", async () => {
    login.mockRejectedValueOnce(new Error("unexpected"));
    const user = userEvent.setup();

    render(<LoginForm />);

    await user.type(screen.getByLabelText(/email/i), "rider@example.com");
    await user.type(screen.getByLabelText(/password/i), "StrongPassw0rd!23");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/something went wrong/i);
    expect(alert).not.toHaveTextContent(/invalid email or password/i);
  });

  it("disables the submit button while the request is in flight", async () => {
    let resolveLogin: () => void = () => {};
    login.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          resolveLogin = resolve;
        }),
    );
    const user = userEvent.setup();

    render(<LoginForm />);

    await user.type(screen.getByLabelText(/email/i), "rider@example.com");
    await user.type(screen.getByLabelText(/password/i), "StrongPassw0rd!23");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(screen.getByRole("button", { name: /signing in/i })).toBeDisabled();

    resolveLogin();
    await waitFor(() => expect(screen.getByRole("button", { name: /sign in/i })).toBeEnabled());
  });
});
