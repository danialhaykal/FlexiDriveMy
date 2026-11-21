import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Mail, ShieldCheck } from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import type { UserRole } from "../../types/auth";
import { Button } from "../ui/Button";
import { Input } from "../ui/Input";

// The role as people say it: a "user" account is a buyer.
export function roleLabel(role: UserRole): string {
  return role === "admin" ? "Admin" : "Buyer";
}

// A read-only fact (email, role) with a small icon - not an input.
function Fact({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <span aria-hidden="true" className="mt-0.5 text-ink-muted">
        {icon}
      </span>
      <div className="min-w-0">
        <span className="block text-small font-medium text-ink">{label}</span>
        <p className="mt-0.5 break-words text-body text-ink">{children}</p>
      </div>
    </div>
  );
}

export function ProfileForm() {
  const { user, updateProfile } = useAuth();
  const [firstName, setFirstName] = useState(user?.first_name ?? "");
  const [lastName, setLastName] = useState(user?.last_name ?? "");
  const [phoneNumber, setPhoneNumber] = useState(user?.phone_number ?? "");
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");

  if (!user) {
    return null;
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setStatus("saving");
    try {
      await updateProfile({
        first_name: firstName,
        last_name: lastName,
        phone_number: phoneNumber,
      });
      setStatus("saved");
    } catch {
      setStatus("error");
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" aria-label="Profile form">
      <div className="flex flex-col gap-4 rounded-control border border-border bg-page-bg p-4">
        <Fact icon={<Mail className="h-4 w-4" />} label="Email">
          {user.email}
        </Fact>
        <Fact icon={<ShieldCheck className="h-4 w-4" />} label="Role">
          {roleLabel(user.role)}
        </Fact>
      </div>
      <Input
        label="First name"
        id="firstName"
        value={firstName}
        onChange={(event) => setFirstName(event.target.value)}
      />
      <Input
        label="Last name"
        id="lastName"
        value={lastName}
        onChange={(event) => setLastName(event.target.value)}
      />
      <Input
        label="Phone number"
        id="phoneNumber"
        value={phoneNumber}
        onChange={(event) => setPhoneNumber(event.target.value)}
      />
      <Button type="submit" isLoading={status === "saving"}>
        {status === "saving" ? "Saving…" : "Save changes"}
      </Button>
      {status === "saved" && (
        <p role="status" className="text-small text-positive-700">
          Profile updated.
        </p>
      )}
      {status === "error" && (
        <p role="alert" className="text-small text-danger-700">
          Could not save changes.
        </p>
      )}
    </form>
  );
}
