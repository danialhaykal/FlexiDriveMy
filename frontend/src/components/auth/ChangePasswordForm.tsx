import { useState } from "react";
import type { FormEvent } from "react";
import { isAxiosError } from "axios";
import { changePasswordRequest } from "../../api/auth";
import { parseApiErrorMessage } from "../../lib/apiErrors";
import { Button } from "../ui/Button";
import { Input } from "../ui/Input";

// QA audit M20: a reasonably-scoped "change password" action for an
// already-authenticated user - see apps.users.serializers.
// ChangePasswordSerializer's own docstring for why a full forgot-
// password-via-email flow is a separate, flagged follow-up instead.

const GENERIC_ERROR = "Could not change your password. Please try again.";

export function ChangePasswordForm() {
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newPassword2, setNewPassword2] = useState("");
  const [status, setStatus] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);

  const mismatch =
    newPassword2.length > 0 && newPassword !== newPassword2 ? "Passwords do not match." : null;

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (mismatch) return;
    setStatus("saving");
    setError(null);
    try {
      await changePasswordRequest({ old_password: oldPassword, new_password: newPassword });
      setStatus("saved");
      setOldPassword("");
      setNewPassword("");
      setNewPassword2("");
    } catch (err) {
      setStatus("idle");
      if (isAxiosError(err) && err.response?.data) {
        setError(parseApiErrorMessage(err.response.data) ?? GENERIC_ERROR);
      } else {
        setError(GENERIC_ERROR);
      }
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" aria-label="Change password form">
      <Input
        label="Current password"
        id="oldPassword"
        type="password"
        autoComplete="current-password"
        required
        value={oldPassword}
        onChange={(event) => {
          setOldPassword(event.target.value);
          setError(null);
        }}
      />
      <Input
        label="New password"
        id="newPassword"
        type="password"
        autoComplete="new-password"
        required
        value={newPassword}
        onChange={(event) => setNewPassword(event.target.value)}
      />
      <Input
        label="Confirm new password"
        id="newPassword2"
        type="password"
        autoComplete="new-password"
        required
        value={newPassword2}
        onChange={(event) => setNewPassword2(event.target.value)}
        error={mismatch ?? undefined}
      />
      <Button type="submit" isLoading={status === "saving"}>
        {status === "saving" ? "Changing…" : "Change password"}
      </Button>
      {status === "saved" && <p role="status" className="text-small text-positive-700">Password changed.</p>}
      {error && (
        <p role="alert" className="text-small text-danger-700">
          {error}
        </p>
      )}
    </form>
  );
}
