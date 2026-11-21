import { useState } from "react";
import type { FormEvent } from "react";
import axios from "axios";
import { useAuth } from "../../context/AuthContext";
import { Button } from "../ui/Button";
import { Input } from "../ui/Input";

interface LoginFormProps {
  onSuccess?: () => void;
}

export function LoginForm({ onSuccess }: LoginFormProps) {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitError(null);
    setIsSubmitting(true);
    try {
      await login(email, password);
      onSuccess?.();
    } catch (err) {
      // Live-walkthrough finding: a bare `catch` previously showed
      // "Invalid email or password." for ANY failure - a 401 (real bad
      // credentials), a 503 while the backend was briefly down, and a
      // dropped connection all looked identical, which is actively
      // misleading for the latter two (the user has no reason to think
      // their own credentials are the problem). AuthContext.login()
      // rethrows the original axios error unchanged, so the real status
      // is readable here.
      if (axios.isAxiosError(err) && err.response?.status === 401) {
        setSubmitError("Invalid email or password.");
      } else if (axios.isAxiosError(err) && !err.response) {
        setSubmitError("Could not reach the server. Please check your connection and try again.");
      } else {
        setSubmitError("Something went wrong. Please try again in a moment.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" aria-label="Login form">
      <Input
        label="Email"
        id="email"
        name="email"
        type="email"
        autoComplete="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <Input
        label="Password"
        id="password"
        name="password"
        type="password"
        autoComplete="current-password"
        required
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />
      {submitError && (
        <p role="alert" className="text-small text-danger-700">
          {submitError}
        </p>
      )}
      <Button type="submit" isLoading={isSubmitting}>
        {isSubmitting ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
