import { useState } from "react";
import type { FormEvent } from "react";
import { isAxiosError } from "axios";
import { registerRequest } from "../../api/auth";
import { parseApiErrorMessage } from "../../lib/apiErrors";
import { Button } from "../ui/Button";
import { Input } from "../ui/Input";

interface RegisterFormProps {
  onSuccess?: () => void;
}

const GENERIC_ERROR = "Registration failed. Please try again.";
const FORM_FIELDS = ["first_name", "last_name", "email", "password", "password2"] as const;
type FormField = (typeof FORM_FIELDS)[number];

// Run 1 fix batch 5 (A1): EVERY message for EVERY field at once, not just the
// first one - DRF's password checks often return several for one field.
function messagesFrom(value: unknown): string[] {
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === "string");
  return typeof value === "string" ? [value] : [];
}

function splitErrors(data: unknown): { fields: Partial<Record<FormField, string>>; other: string | null } {
  if (!data || typeof data !== "object") return { fields: {}, other: null };
  const record = data as Record<string, unknown>;
  const fields: Partial<Record<FormField, string>> = {};
  const other: string[] = [];
  for (const [key, value] of Object.entries(record)) {
    const messages = messagesFrom(value);
    if (messages.length === 0) continue;
    if ((FORM_FIELDS as readonly string[]).includes(key)) fields[key as FormField] = messages.join(" ");
    else other.push(...messages);
  }
  return { fields, other: other.length ? other.join(" ") : null };
}

export function RegisterForm({ onSuccess }: RegisterFormProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<FormField, string>>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  // QA audit M20: checked client-side too, not just left to the server's
  // 400 - instant feedback rather than a round trip for the single most
  // common registration typo.
  const passwordMismatch =
    password2.length > 0 && password !== password2 ? "Passwords do not match." : null;

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (passwordMismatch) return;
    setSubmitError(null);
    setFieldErrors({});
    setIsSubmitting(true);
    try {
      await registerRequest({
        email,
        password,
        password2,
        first_name: firstName,
        last_name: lastName,
      });
      onSuccess?.();
    } catch (err) {
      if (isAxiosError(err) && err.response?.data) {
        const { fields, other } = splitErrors(err.response.data);
        setFieldErrors(fields);
        // Anything not tied to a field (e.g. "detail") still shows below the form.
        setSubmitError(other ?? (Object.keys(fields).length ? null : parseApiErrorMessage(err.response.data) ?? GENERIC_ERROR));
      } else {
        setSubmitError(GENERIC_ERROR);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" aria-label="Registration form">
      <div className="grid grid-cols-2 gap-4">
        <Input
          label="First name"
          id="firstName"
          value={firstName}
          onChange={(event) => setFirstName(event.target.value)}
          error={fieldErrors.first_name}
        />
        <Input
          label="Last name"
          id="lastName"
          value={lastName}
          onChange={(event) => setLastName(event.target.value)}
          error={fieldErrors.last_name}
        />
      </div>
      <Input
        label="Email"
        id="email"
        type="email"
        autoComplete="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        error={fieldErrors.email}
      />
      <Input
        label="Password"
        id="password"
        type="password"
        autoComplete="new-password"
        required
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        error={fieldErrors.password}
      />
      {/* FX-2 (item 11): the rules the backend enforces - Django's four
          AUTH_PASSWORD_VALIDATORS in config/settings.py, defaults unchanged
          (MinimumLengthValidator's 8). The server's own messages still decide. */}
      <ul id="password-rules" className="-mt-2 list-disc pl-5 text-caption text-ink-muted">
        <li>At least 8 characters</li>
        <li>Not too similar to your name or email</li>
        <li>Not a commonly used password</li>
        <li>Not made of numbers only</li>
      </ul>
      <Input
        label="Confirm password"
        id="password2"
        type="password"
        autoComplete="new-password"
        required
        value={password2}
        onChange={(event) => setPassword2(event.target.value)}
        error={passwordMismatch ?? fieldErrors.password2}
      />
      {submitError && (
        <p role="alert" className="text-small text-danger-700">
          {submitError}
        </p>
      )}
      <Button type="submit" isLoading={isSubmitting}>
        {isSubmitting ? "Creating account…" : "Create account"}
      </Button>
      {/* FX-2 (item 11) */}
      <p className="text-caption text-ink-muted">We use your details only to run your comparisons.</p>
    </form>
  );
}
