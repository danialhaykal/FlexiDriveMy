import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChangePasswordForm } from "./ChangePasswordForm";
import { changePasswordRequest } from "../../api/auth";

vi.mock("../../api/auth", () => ({
  changePasswordRequest: vi.fn(),
}));

const mockedChangePasswordRequest = vi.mocked(changePasswordRequest);

describe("ChangePasswordForm", () => {
  beforeEach(() => {
    mockedChangePasswordRequest.mockReset();
  });

  it("submits old/new password and shows a success message", async () => {
    mockedChangePasswordRequest.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<ChangePasswordForm />);

    await user.type(screen.getByLabelText("Current password"), "OldPass1!");
    await user.type(screen.getByLabelText("New password"), "NewStrongPass1!");
    await user.type(screen.getByLabelText("Confirm new password"), "NewStrongPass1!");
    await user.click(screen.getByRole("button", { name: /change password/i }));

    expect(mockedChangePasswordRequest).toHaveBeenCalledWith({
      old_password: "OldPass1!",
      new_password: "NewStrongPass1!",
    });
    expect(await screen.findByText("Password changed.")).toBeInTheDocument();
  });

  it("blocks submission and shows an inline error when the new passwords differ", async () => {
    const user = userEvent.setup();
    render(<ChangePasswordForm />);

    await user.type(screen.getByLabelText("Current password"), "OldPass1!");
    await user.type(screen.getByLabelText("New password"), "NewStrongPass1!");
    await user.type(screen.getByLabelText("Confirm new password"), "SomethingElse1!");

    expect(await screen.findByText("Passwords do not match.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /change password/i }));
    expect(mockedChangePasswordRequest).not.toHaveBeenCalled();
  });

  it("surfaces the server's 'Current password is incorrect.' message", async () => {
    mockedChangePasswordRequest.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 400, data: { old_password: ["Current password is incorrect."] } },
    });
    const user = userEvent.setup();
    render(<ChangePasswordForm />);

    await user.type(screen.getByLabelText("Current password"), "WrongPass1!");
    await user.type(screen.getByLabelText("New password"), "NewStrongPass1!");
    await user.type(screen.getByLabelText("Confirm new password"), "NewStrongPass1!");
    await user.click(screen.getByRole("button", { name: /change password/i }));

    expect(await screen.findByText("Current password is incorrect.")).toBeInTheDocument();
  });
});
