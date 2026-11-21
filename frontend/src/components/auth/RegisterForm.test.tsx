import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RegisterForm } from "./RegisterForm";
import { registerRequest } from "../../api/auth";

vi.mock("../../api/auth", () => ({
  registerRequest: vi.fn(),
}));

const mockedRegisterRequest = vi.mocked(registerRequest);

async function fillForm(user: ReturnType<typeof userEvent.setup>, password = "AStrongPass1!", password2 = password) {
  await user.type(screen.getByLabelText("Email"), "new@example.com");
  await user.type(screen.getByLabelText("Password"), password);
  await user.type(screen.getByLabelText("Confirm password"), password2);
}

describe("RegisterForm", () => {
  beforeEach(() => {
    mockedRegisterRequest.mockReset();
  });

  // --- QA audit M20 -------------------------------------------------------

  it("sends password2 and calls onSuccess when the passwords match", async () => {
    mockedRegisterRequest.mockResolvedValueOnce({
      id: 1, email: "new@example.com", first_name: "", last_name: "", phone_number: "",
      role: "user", date_joined: "2026-01-01T00:00:00Z",
    });
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    render(<RegisterForm onSuccess={onSuccess} />);

    await fillForm(user);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(mockedRegisterRequest).toHaveBeenCalledWith(
      expect.objectContaining({
        email: "new@example.com",
        password: "AStrongPass1!",
        password2: "AStrongPass1!",
      }),
    );
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("shows an inline error and never submits when the two passwords differ", async () => {
    const user = userEvent.setup();
    render(<RegisterForm />);

    await fillForm(user, "AStrongPass1!", "ADifferentPass1!");

    expect(await screen.findByText("Passwords do not match.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /create account/i }));
    expect(mockedRegisterRequest).not.toHaveBeenCalled();
  });

  it("surfaces the server's field-level message (e.g. a mismatch DRF itself caught) via the shared parser", async () => {
    mockedRegisterRequest.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 400, data: { password2: ["Passwords do not match."] } },
    });
    const user = userEvent.setup();
    render(<RegisterForm />);

    await fillForm(user);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    // Run 1 fix batch 5 (A1): shown under its own field.
    expect(await screen.findByText("Passwords do not match.")).toBeInTheDocument();
    expect(screen.getByLabelText("Confirm password")).toHaveAccessibleDescription("Passwords do not match.");
  });

  // --- Run 1 fix batch 5 (A1): every field error at once -----------------------

  it("shows every field's errors at once, each under its own field, all messages per field", async () => {
    mockedRegisterRequest.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 400,
        data: {
          email: ["A user with that email already exists."],
          password: ["This password is too short.", "This password is too common."],
          first_name: ["Ensure this field has no more than 150 characters."],
        },
      },
    });
    const user = userEvent.setup();
    render(<RegisterForm />);

    await fillForm(user);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByText("A user with that email already exists.")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveAccessibleDescription(
      "This password is too short. This password is too common.",
    );
    expect(screen.getByLabelText("First name")).toHaveAccessibleDescription(
      "Ensure this field has no more than 150 characters.",
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // nothing left over for the form-level box
  });

  it("keeps a message that belongs to no field in the box under the form", async () => {
    mockedRegisterRequest.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 429, data: { detail: "Request was throttled. Expected available in 60 seconds." } },
    });
    const user = userEvent.setup();
    render(<RegisterForm />);

    await fillForm(user);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Request was throttled.");
  });
});

// FX-2 (item 11): the password rules Django enforces (AUTH_PASSWORD_VALIDATORS, defaults) and a privacy line.
describe("RegisterForm password rules", () => {
  it("lists the backend's four password rules and the privacy note", () => {
    render(<RegisterForm />);

    const rules = document.getElementById("password-rules")!;
    expect(Array.from(rules.querySelectorAll("li")).map((li) => li.textContent)).toEqual([
      "At least 8 characters",
      "Not too similar to your name or email",
      "Not a commonly used password",
      "Not made of numbers only",
    ]);
    expect(screen.getByText("We use your details only to run your comparisons.")).toBeInTheDocument();
  });
});
