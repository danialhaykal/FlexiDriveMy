import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ProfilePage } from "./ProfilePage";
import { useAuth } from "../context/AuthContext";
import { changePasswordRequest } from "../api/auth";
import type { AuthUser } from "../types/auth";

// Redesign UI-5: the Profile page's layout - a header with the name and role, a
// "Personal details" card and a "Change password" card. The forms' fields,
// rules and messages are unchanged.

vi.mock("../context/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("../api/auth", () => ({ changePasswordRequest: vi.fn() }));

const updateProfile = vi.fn();

function signIn(overrides: Partial<AuthUser> = {}) {
  vi.mocked(useAuth).mockReturnValue({
    user: {
      id: 8, email: "buyer@example.com", first_name: "Aina", last_name: "Rahman", phone_number: "+60 12-345 6789",
      role: "user", date_joined: "2026-01-01", ...overrides,
    },
    isAuthenticated: true, isLoading: false, error: null, login: vi.fn(), logout: vi.fn(), updateProfile,
  });
}

describe("ProfilePage", () => {
  beforeEach(() => {
    vi.mocked(useAuth).mockReset();
    vi.mocked(changePasswordRequest).mockReset();
    updateProfile.mockReset();
  });

  it("shows the name and a 'Buyer' role badge in the header", () => {
    signIn();
    render(<ProfilePage />);

    const header = screen.getByRole("heading", { level: 1, name: "Your profile" }).closest("header") as HTMLElement;
    expect(within(header).getByText("Aina Rahman")).toBeInTheDocument();
    expect(within(header).getByText("Buyer")).toHaveAttribute("data-tone", "neutral");
  });

  it("falls back to the email when there is no name, and says 'Admin' for an admin", () => {
    signIn({ first_name: "", last_name: "", role: "admin", email: "admin@example.com" });
    render(<ProfilePage />);

    const header = screen.getByRole("heading", { level: 1, name: "Your profile" }).closest("header") as HTMLElement;
    expect(within(header).getByText("admin@example.com")).toBeInTheDocument();
    expect(within(header).getByText("Admin")).toBeInTheDocument();
  });

  it("has a Personal details card (email and role as facts, then the fields) and a Change password card", () => {
    signIn();
    render(<ProfilePage />);

    const personal = screen.getByRole("heading", { level: 2, name: "Personal details" }).parentElement as HTMLElement;
    expect(within(personal).getByText("buyer@example.com")).toBeInTheDocument();
    expect(within(personal).getByLabelText("First name")).toHaveValue("Aina");
    expect(within(personal).getByLabelText("Last name")).toHaveValue("Rahman");
    expect(within(personal).getByLabelText("Phone number")).toHaveValue("+60 12-345 6789");
    expect(within(personal).getByRole("button", { name: "Save changes" })).toBeInTheDocument();

    const password = screen.getByRole("heading", { level: 2, name: "Change password" }).parentElement as HTMLElement;
    expect(within(password).getByLabelText("Current password")).toHaveAttribute("type", "password");
    expect(within(password).getByLabelText("New password")).toBeInTheDocument();
    expect(within(password).getByLabelText("Confirm new password")).toBeInTheDocument();
  });

  it("saves personal details with the same request and message as before", async () => {
    signIn();
    updateProfile.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<ProfilePage />);

    await user.clear(screen.getByLabelText("First name"));
    await user.type(screen.getByLabelText("First name"), "Nur");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(updateProfile).toHaveBeenCalledWith({ first_name: "Nur", last_name: "Rahman", phone_number: "+60 12-345 6789" });
    expect(await screen.findByRole("status")).toHaveTextContent("Profile updated.");
  });

  it("keeps the same error message when saving fails", async () => {
    signIn();
    updateProfile.mockRejectedValueOnce(new Error("400"));
    const user = userEvent.setup();
    render(<ProfilePage />);

    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save changes.");
  });
});
