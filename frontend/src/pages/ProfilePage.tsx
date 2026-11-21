import { KeyRound, UserRound } from "lucide-react";
import type { ReactNode } from "react";
import { ChangePasswordForm } from "../components/auth/ChangePasswordForm";
import { ProfileForm, roleLabel } from "../components/auth/ProfileForm";
import { useAuth } from "../context/AuthContext";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { Badge } from "../components/ui/Badge";
import { Card } from "../components/ui/Card";
import { PageHeader } from "../components/ui/PageHeader";

// Account settings (name, phone, password). Redesign UI-5: a page header with
// the user's name and role, then two cards - side by side from lg, stacked
// below. The forms, their rules and their messages are unchanged.

function SectionCard({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <Card className="h-full">
      <h2 className="flex items-center gap-2 text-h3 font-bold text-ink">
        <span
          aria-hidden="true"
          className="flex h-8 w-8 items-center justify-center rounded-control bg-primary-50 text-primary-700"
        >
          {icon}
        </span>
        {title}
      </h2>
      <div className="mt-6">{children}</div>
    </Card>
  );
}

export function ProfilePage() {
  useDocumentTitle("Your Profile");
  const { user } = useAuth();
  const fullName = [user?.first_name, user?.last_name].filter(Boolean).join(" ");

  return (
    <div className="mx-auto max-w-5xl px-4 pb-16 pt-8 sm:pt-10">
      <PageHeader
        title="Your profile"
        subtitle={fullName || user?.email}
        actions={user && <Badge tone="neutral">{roleLabel(user.role)}</Badge>}
      />
      <div className="mt-6 grid grid-cols-1 items-start gap-6 lg:grid-cols-2">
        <SectionCard icon={<UserRound className="h-4 w-4" />} title="Personal details">
          <ProfileForm />
        </SectionCard>
        <SectionCard icon={<KeyRound className="h-4 w-4" />} title="Change password">
          <ChangePasswordForm />
        </SectionCard>
      </div>
    </div>
  );
}
