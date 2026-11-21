import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Car, ShieldCheck, Wallet } from "lucide-react";
import { fetchFinancialProfile, saveFinancialProfile } from "../api/profile";
import { parseApiFieldErrors } from "../lib/apiErrors";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { DEFAULT_TENURE_MONTHS } from "../lib/defaults";
import { useMileageBandOptions } from "../hooks/useMileageBandOptions";
import {
  DEFAULT_MAX_DSR_PERCENT,
  NCD_HELP_TEXT,
  NCD_LABEL,
  NCD_OPTIONS,
  OWNERSHIP_PREFERENCE_OPTIONS,
  mapAnnualMileageBandToMileageBand,
} from "../types/profile";
import type { FinancialProfilePayload, OwnershipPreference } from "../types/profile";
import type { MileageBand } from "../types/comparisons";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { InfoExpander } from "../components/ui/InfoExpander";
import { Input } from "../components/ui/Input";
import { LoadingSkeleton } from "../components/ui/LoadingSkeleton";
import { PageHeader } from "../components/ui/PageHeader";
import { RangeSlider } from "../components/ui/RangeSlider";
import { Select } from "../components/ui/Select";

// UC003 - Financial & Lifestyle Profiling Input. Backend is apps.profiles
// (FinancialProfile, a singleton-per-user upsert resource) - already
// complete; this is purely the missing admin... no, USER-facing page for
// it (every authenticated user has exactly one profile, not an admin-only
// resource like Batch 6A/6B's pages). Distinct from ProfilePage.tsx
// (account settings: name/email/password) - this is the financial/
// lifestyle baseline UC006/UC007 read elsewhere, a different concept
// entirely.
//
// Redesign UI-5: the same fields, rules, messages and saved values, in three
// groups (Budget / How you drive / Insurance and financing) with one save bar
// that stays at the bottom of the screen while the form is in view.

// One labelled group of fields: a card with a small icon heading and a
// 2-column grid from md.
function FieldGroup({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <Card>
      <h2 className="flex items-center gap-2 text-h3 font-bold text-ink">
        <span
          aria-hidden="true"
          className="flex h-8 w-8 items-center justify-center rounded-control bg-primary-50 text-primary-700"
        >
          {icon}
        </span>
        {title}
      </h2>
      <div className="mt-5 grid grid-cols-1 gap-5 md:grid-cols-2">{children}</div>
    </Card>
  );
}

function emptyPayload(): FinancialProfilePayload {
  return {
    monthly_budget: "",
    preferred_tenure_months: DEFAULT_TENURE_MONTHS,
    annual_mileage_band: "" as MileageBand,
    ownership_preference: "" as OwnershipPreference,
    shariah_compliant_required: false,
    ncd_percent: "0.00",
    monthly_income: "",
    max_dsr_percent: DEFAULT_MAX_DSR_PERCENT,
  };
}

export function FinancialProfilePage() {
  useDocumentTitle("Financial Profile");

  const [form, setForm] = useState<FinancialProfilePayload>(emptyPayload());
  // The mileage bands offered: the one shared list the compare screens use.
  const mileageBandOptions = useMileageBandOptions();
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<"idle" | "saving" | "saved">("idle");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setLoadError(null);
    fetchFinancialProfile()
      .then((profile) => {
        if (cancelled) return;
        if (profile) {
          setForm({
            monthly_budget: profile.monthly_budget,
            preferred_tenure_months: profile.preferred_tenure_months,
            // An old stored value (a literal km figure) still loads: it maps to the
            // band whose range starts there instead of leaving the box blank.
            annual_mileage_band: mapAnnualMileageBandToMileageBand(profile.annual_mileage_band),
            ownership_preference: profile.ownership_preference,
            shariah_compliant_required: profile.shariah_compliant_required,
            ncd_percent: profile.ncd_percent ?? "0.00",
            monthly_income: profile.monthly_income ?? "",
            max_dsr_percent: profile.max_dsr_percent ?? DEFAULT_MAX_DSR_PERCENT,
          });
        }
      })
      .catch(() => {
        if (!cancelled) setLoadError("Could not load your saved financial profile. Please try again.");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setStatus("saving");
    setFieldErrors({});
    try {
      const saved = await saveFinancialProfile(form);
      setForm({
        monthly_budget: saved.monthly_budget,
        preferred_tenure_months: saved.preferred_tenure_months,
        annual_mileage_band: mapAnnualMileageBandToMileageBand(saved.annual_mileage_band),
        ownership_preference: saved.ownership_preference,
        shariah_compliant_required: saved.shariah_compliant_required,
        ncd_percent: saved.ncd_percent ?? "0.00",
        monthly_income: saved.monthly_income ?? "",
        max_dsr_percent: saved.max_dsr_percent ?? DEFAULT_MAX_DSR_PERCENT,
      });
      setStatus("saved");
    } catch (err: unknown) {
      setFieldErrors(parseApiFieldErrors((err as { response?: { data?: unknown } })?.response?.data));
      setStatus("idle");
    }
  }

  if (isLoading) {
    return (
      <div className="mx-auto max-w-4xl px-4 pb-16 pt-8 sm:pt-10">
        <LoadingSkeleton className="h-96 w-full" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 pb-16 pt-8 sm:pt-10">
      <PageHeader
        title="Financial profile"
        subtitle="These settings fill in your comparisons for you. You can still change them on any comparison."
      />

      {loadError && (
        <div role="alert" className="mt-6 flex flex-wrap items-center gap-3 rounded-card border border-danger-200 bg-danger-50 p-4">
          <p className="text-small text-danger-700">{loadError}</p>
          <Button variant="secondary" onClick={() => setReloadKey((key) => key + 1)}>
            Try again
          </Button>
        </div>
      )}

      {/* scroll-mb keeps a field that gets focus clear of the save bar. */}
      <form className="mt-6 flex flex-col gap-6 [&_input]:scroll-mb-28 [&_select]:scroll-mb-28" onSubmit={handleSubmit}>
        <FieldGroup icon={<Wallet className="h-4 w-4" />} title="Budget">
          <Input
            label="Monthly budget (RM)"
            value={form.monthly_budget}
            onChange={(e) => setForm((prev) => ({ ...prev, monthly_budget: e.target.value }))}
            error={fieldErrors.monthly_budget}
          />
          {/* Run 1 fix batch 5: prefills for the AI Recommendation and
              Affordability tabs - still changeable there per comparison. */}
          <Input
            // FX-2 (item 7): gross income, before tax (DSR is measured on gross income).
            label="Monthly income (gross, RM)"
            value={form.monthly_income}
            onChange={(e) => setForm((prev) => ({ ...prev, monthly_income: e.target.value }))}
            error={fieldErrors.monthly_income}
          />
          <Input
            label="Max DSR limit (%)"
            value={form.max_dsr_percent}
            onChange={(e) => setForm((prev) => ({ ...prev, max_dsr_percent: e.target.value }))}
            error={fieldErrors.max_dsr_percent}
          />
          <InfoExpander summary="What is this used for?" className="md:self-end md:pb-2.5">
            Used to start the AI Recommendation and Affordability tabs; you can change them for any
            comparison. Income is optional.
          </InfoExpander>
        </FieldGroup>

        <FieldGroup icon={<Car className="h-4 w-4" />} title="How you drive">
          <div className="flex flex-col gap-2 md:col-span-2">
            <RangeSlider
              label="Preferred tenure"
              value={form.preferred_tenure_months}
              min={12}
              max={108}
              step={1}
              formatValue={(v) => `${v} months`}
              onChange={(value) => setForm((prev) => ({ ...prev, preferred_tenure_months: value }))}
            />
            {fieldErrors.preferred_tenure_months && (
              <p className="text-small text-danger-700">{fieldErrors.preferred_tenure_months}</p>
            )}
          </div>

          <Select
            label="Annual mileage band"
            value={form.annual_mileage_band}
            onChange={(e) =>
              setForm((prev) => ({
                ...prev,
                annual_mileage_band: e.target.value as MileageBand,
              }))
            }
            options={[{ value: "", label: "Select..." }, ...mileageBandOptions]}
            error={fieldErrors.annual_mileage_band}
          />

          <Select
            label="Ownership preference"
            value={form.ownership_preference}
            onChange={(e) =>
              setForm((prev) => ({
                ...prev,
                ownership_preference: e.target.value as OwnershipPreference,
              }))
            }
            options={[{ value: "", label: "Select..." }, ...OWNERSHIP_PREFERENCE_OPTIONS]}
            error={fieldErrors.ownership_preference}
          />
        </FieldGroup>

        <FieldGroup icon={<ShieldCheck className="h-4 w-4" />} title="Insurance and financing">
          {/* Lowers insurance in the owner's running costs (Hire Purchase, GFV,
              TCO); never the subscription fee. Applied by the server. */}
          <Select
            label={NCD_LABEL}
            value={form.ncd_percent}
            onChange={(e) => setForm((prev) => ({ ...prev, ncd_percent: e.target.value }))}
            options={NCD_OPTIONS}
            helpText={NCD_HELP_TEXT}
            helpSummary="Where do I find this?"
            error={fieldErrors.ncd_percent}
          />

          {/* The stored field keeps its name (shariah_compliant_required), but
              all it does is relabel the Hire Purchase rate as a "profit rate"
              and add an "indicative" note - nothing is filtered, repriced or
              certified, so the wording must not imply otherwise. The note stays
              visible beside the checkbox. */}
          <div className="flex flex-col gap-1 md:pt-7">
            <label className="flex items-center gap-2 text-small font-medium text-ink">
              <input
                type="checkbox"
                checked={form.shariah_compliant_required}
                aria-describedby="islamic-financing-help"
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, shariah_compliant_required: e.target.checked }))
                }
                className="h-4 w-4 rounded border-border accent-primary-600"
              />
              I prefer Islamic financing (AITAB / profit rate)
            </label>
            <p id="islamic-financing-help" className="pl-6 text-caption text-ink-muted">
              Islamic hire purchase uses a profit rate instead of interest. This app does not yet
              price Islamic products separately, so figures are the conventional flat-rate estimates
              as an indicative guide only.
            </p>
          </div>
        </FieldGroup>

        {fieldErrors.detail && <p className="text-small text-danger-700">{fieldErrors.detail}</p>}

        {/* One save bar, at the bottom of the screen while the form is in view
            (sticky, so at rest it sits in its own place below the last field;
            under the Menu drawer's layer). */}
        <div className="sticky bottom-0 z-20 -mx-4 flex flex-wrap items-center gap-3 border-t border-border bg-surface/95 px-4 py-3 shadow-[0_-4px_12px_rgba(15,23,42,0.06)] backdrop-blur sm:mx-0 sm:rounded-card sm:border">
          <Button type="submit" isLoading={status === "saving"}>
            Save &amp; Apply Baseline
          </Button>
          {status === "saved" && (
            <p role="status" className="text-small font-medium text-positive-700">
              Baseline saved.
            </p>
          )}
        </div>
      </form>
    </div>
  );
}
