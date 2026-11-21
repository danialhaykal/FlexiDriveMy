import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import axios from "axios";
import {
  Calculator,
  ChevronDown,
  FileText,
  Fuel,
  Percent,
  Receipt,
  Scale,
  SlidersHorizontal,
  TrendingDown,
} from "lucide-react";
import {
  archiveContractPenaltyRule,
  archiveInterestRate,
  archiveResidualValueMatrixEntry,
  archiveSubscriptionPlan,
  createContractPenaltyRule,
  createInterestRate,
  createResidualValueMatrixEntry,
  createSubscriptionPlan,
  fetchContractPenaltyRules,
  fetchInterestRates,
  fetchMCDAWeights,
  fetchOperatingCosts,
  fetchResidualEstimates,
  fetchResidualValueMatrix,
  fetchSubscriptionEstimates,
  fetchSubscriptionPlans,
  updateContractPenaltyRule,
  updateInterestRate,
  updateMCDAWeights,
  updateResidualValueMatrixEntry,
  updateSubscriptionPlan,
} from "../api/policy";
import type {
  ContractPenaltyRuleWritePayload,
  ResidualValueMatrixWritePayload,
  SubscriptionPlanWritePayload,
} from "../api/policy";
import { fetchAdminBrands, fetchAdminVehicles } from "../api/adminFleet";
import { listTotal } from "../api/allPages";
import { parseApiErrorMessage, parseApiFieldErrors } from "../lib/apiErrors";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { formatCurrency, formatPercent } from "../lib/formatCurrency";
import {
  formatKw,
  formatKwRange,
  formatPlainAmount,
  formatRatioPercent,
  formatRatioPoints,
  formatWeightPercent,
  splitSourceNotes,
} from "../lib/formatPolicy";
import { formatAdminDate, formatAdminDateTime } from "../lib/formatAdminDate";
import { bandNameFromLabel } from "../lib/mileageBandName";
import { useMileageBandOptions } from "../hooks/useMileageBandOptions";
import { MILEAGE_BAND_OPTIONS } from "../types/comparisons";
import { MCDA_CRITERION_LABELS } from "../types/policy";
import type {
  ContractPenaltyRule,
  InterestRate,
  MCDACriteriaWeight,
  MCDACriterion,
  OperatingCostsResponse,
  RoadTaxCcBandRow,
  ResidualEstimatesResponse,
  ResidualValueMatrixEntry,
  SubscriptionEstimatesResponse,
  SubscriptionPlan,
} from "../types/policy";
import type { AdminBrand, AdminVehicle } from "../types/adminFleet";
import { AdminListToolbar, NoMatchingRows, useAdminListFilter } from "../components/admin/AdminListToolbar";
import { RowActionsMenu } from "../components/admin/RowActionsMenu";
import type { RowAction } from "../components/admin/RowActionsMenu";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { EmptyState } from "../components/ui/EmptyState";
import { InfoExpander } from "../components/ui/InfoExpander";
import { Input } from "../components/ui/Input";
import { ListCapNotice } from "../components/ui/ListCapNotice";
import { LoadingSkeleton } from "../components/ui/LoadingSkeleton";
import { PageHeader } from "../components/ui/PageHeader";
import { Select } from "../components/ui/Select";
import { Table } from "../components/ui/Table";
import { Tabs } from "../components/ui/Tabs";
import { cn } from "../components/ui/cn";

// Batch 6A, UC011 - Policy & Rate Configuration. Every section below
// follows the same shape: fetch its own list on mount (Tabs.Panel
// unmounts an inactive panel, so switching tabs naturally refetches -
// see Tabs.tsx's own docstring for why that's the deliberate design),
// an add/edit form that shows the server's EXACT verbatim validation
// copy per field while preserving every other entered value (never
// cleared on a failed submit - UC011's alternate flow), and archive via
// the shared ConfirmDialog. the project spec: every boundary rule (e.g. the
// 0.01%-15.00% interest rate range, the MCDA weights summing to 1.0) is
// validated and enforced in Python alone - nothing here re-derives or
// pre-empts a server validation rule, it only displays what the server
// already decided.
//
// Redesign UI-6a: the 8 sections are a vertical list on the left from lg and
// a "Section" select below it; each section opens with a heading, one purpose
// line and the longer explanation folded in "How this is used". The four
// editable lists share the admin toolbar (Active by default) and a row menu.
// Ratios are SHOWN as percentages / points; forms keep their own units and
// send exactly what they sent before.

const GENERIC_ERROR = "Could not save this record. Please try again.";
const EDIT_CONFLICT_MESSAGE = "This record was changed by someone else. Reload to see the latest version.";
// UC011: the FYP1 report's label for saving a policy change.
const SAVE_LABEL = "Apply Policy Update";
const ARCHIVED_ROW_CLASS = "bg-page-bg [&>td]:text-ink-muted";

// Run 3 fix batch 5 (F-18): display-only formatting for the read-only tables -
// the values are shown as the API sent them, just with their units.
// "2.00" -> "2", "1.50" -> "1.5".
function trimNumber(value: string): string {
  const n = Number(value);
  return Number.isNaN(n) ? value : n.toLocaleString("en-MY", { maximumFractionDigits: 2 });
}

// A whole number of km a year as "N,NNN km/year" (en-MY grouping).
function formatKmPerYear(value: number | string): string {
  const n = Number(value);
  return Number.isNaN(n) ? String(value) : `${n.toLocaleString("en-MY")} km/year`;
}

function errorsFromCatch(err: unknown): Record<string, string> {
  if (axios.isAxiosError(err) && err.response?.status === 400) {
    return parseApiFieldErrors(err.response.data);
  }
  // Run 1 fix batch 5 (G7): someone else saved this row since it was loaded.
  // The form (and every typed value) stays open; only this message shows.
  if (axios.isAxiosError(err) && err.response?.status === 409) {
    return { detail: parseApiErrorMessage(err.response.data) ?? EDIT_CONFLICT_MESSAGE };
  }
  return { detail: GENERIC_ERROR };
}

interface SectionProps {
  brands: AdminBrand[];
}

// Same rule as AdminFleetPage's vehicleFormBrandOptions: a new row may only
// be filed under an ACTIVE brand, but editing an existing row keeps that
// row's own brand selectable even if the brand has since been archived.
function formBrandOptions(brands: AdminBrand[], editingRowBrandId: number | null | undefined) {
  return [
    { value: "", label: "Select a brand..." },
    ...brands
      .filter((b) => b.is_active || b.id === editingRowBrandId)
      .map((b) => ({ value: String(b.id), label: b.is_active ? b.name : `${b.name} (archived)` })),
  ];
}

// A section's opening: heading, one purpose line, and the longer explanation folded.
function SectionIntro({ title, purpose, children }: { title: string; purpose: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <h2 className="text-h2 font-bold text-ink">{title}</h2>
      <p className="text-small text-ink">{purpose}</p>
      {children && <InfoExpander summary="How this is used">{children}</InfoExpander>}
    </div>
  );
}

function StatusBadge({ isActive }: { isActive: boolean }) {
  return isActive ? <Badge tone="positive">Active</Badge> : <Badge tone="neutral">Archived</Badge>;
}

function editAndArchiveActions(isActive: boolean, onEdit: () => void, onArchive: () => void): RowAction[] {
  return isActive
    ? [
        { label: "Edit", onSelect: onEdit },
        { label: "Archive", onSelect: onArchive, tone: "danger" },
      ]
    : [{ label: "Edit", onSelect: onEdit }];
}

function InterestRatesSection({ brands }: SectionProps) {
  const [rates, setRates] = useState<InterestRate[]>([]);
  const [ratesTotal, setRatesTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [brand, setBrand] = useState<number | "">("");
  const [ratePercent, setRatePercent] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [archiveTargetId, setArchiveTargetId] = useState<number | null>(null);
  const list = useAdminListFilter(rates, (rate) => rate.is_active, (rate) => rate.brand_name);

  useEffect(() => {
    fetchInterestRates()
      .then((data) => {
        setRates(data);
        setRatesTotal(listTotal(data));
      })
      .finally(() => setIsLoading(false));
  }, []);

  function openAdd() {
    setEditingId(null);
    setBrand("");
    setRatePercent("");
    setErrors({});
    setIsFormOpen(true);
  }

  function openEdit(rate: InterestRate) {
    setEditingId(rate.id);
    setBrand(rate.brand);
    setRatePercent(rate.rate_percent);
    setErrors({});
    setIsFormOpen(true);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setIsSubmitting(true);
    setErrors({});
    try {
      const payload = { brand, rate_percent: ratePercent };
      const saved =
        editingId === null
          ? await createInterestRate(payload)
          : await updateInterestRate(editingId, { ...payload, updated_at: rates.find((r) => r.id === editingId)?.updated_at });
      setRates((prev) =>
        editingId === null ? [...prev, saved] : prev.map((r) => (r.id === saved.id ? saved : r)),
      );
      setIsFormOpen(false);
    } catch (err: unknown) {
      setErrors(errorsFromCatch(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleConfirmArchive() {
    if (archiveTargetId === null) return;
    await archiveInterestRate(archiveTargetId);
    setRates((prev) => prev.map((r) => (r.id === archiveTargetId ? { ...r, is_active: false } : r)));
    setArchiveTargetId(null);
  }

  if (isLoading) return <LoadingSkeleton className="h-64 w-full" />;

  const brandOptions = formBrandOptions(brands, rates.find((r) => r.id === editingId)?.brand);

  return (
    <div className="flex flex-col gap-6">
      <SectionIntro
        title="Interest Rates"
        purpose="Each brand's flat campaign rate, used by Hire Purchase and GFV Leasing."
      >
        The dealer's flat rate on the original balance, as dealers quote it. The app works out the
        effective (reducing-balance) rate from it for display beside it; the rate entered here is
        always the flat one.
      </SectionIntro>
      {isFormOpen && (
        <Card>
          <form className="grid grid-cols-1 gap-4 md:grid-cols-2" onSubmit={handleSubmit}>
            <Select
              label="Brand"
              value={brand === "" ? "" : String(brand)}
              onChange={(e) => setBrand(e.target.value === "" ? "" : Number(e.target.value))}
              options={brandOptions}
              error={errors.brand}
            />
            <div className="flex flex-col gap-1.5">
              <Input
                label="Flat rate (% p.a.)"
                value={ratePercent}
                onChange={(e) => setRatePercent(e.target.value)}
                error={errors.rate_percent}
              />
              <p className="text-caption text-ink-muted">
                The dealer's flat campaign rate on the original balance. The app derives the effective
                (reducing-balance) rate from it - do not enter an effective rate here.
              </p>
            </div>
            {errors.detail && <p className="md:col-span-2 text-small text-danger-700">{errors.detail}</p>}
            <div className="flex gap-2 md:col-span-2">
              <Button type="submit" isLoading={isSubmitting}>
                {editingId === null ? "Create" : SAVE_LABEL}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setIsFormOpen(false)}>
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      )}

      <Card padding="none">
        <div className="p-4 sm:p-6">
          <AdminListToolbar
            searchLabel="Search interest rates"
            {...list.toolbarProps}
            action={!isFormOpen && <Button onClick={openAdd}>Add Interest Rate</Button>}
          />
        </div>
        <Table>
          <Table.Head>
            <Table.Row>
              <Table.HeaderCell>Brand</Table.HeaderCell>
              <Table.HeaderCell numeric>Flat rate</Table.HeaderCell>
              <Table.HeaderCell>Status</Table.HeaderCell>
              <Table.HeaderCell>
                <span className="sr-only">Actions</span>
              </Table.HeaderCell>
            </Table.Row>
          </Table.Head>
          <Table.Body>
            {list.visible.map((rate) => (
              <Table.Row key={rate.id} className={rate.is_active ? undefined : ARCHIVED_ROW_CLASS}>
                <Table.Cell>{rate.brand_name}</Table.Cell>
                {/* Run 3 fix batch 5 (F-18): 2 dp with its unit, like the buyer screens (the API keeps 4 dp). */}
                <Table.Cell numeric>{formatPercent(rate.rate_percent)} flat p.a.</Table.Cell>
                <Table.Cell>
                  <StatusBadge isActive={rate.is_active} />
                </Table.Cell>
                <Table.Cell className="w-12 text-right">
                  <RowActionsMenu
                    label={`Actions for ${rate.brand_name} interest rate`}
                    actions={editAndArchiveActions(rate.is_active, () => openEdit(rate), () => setArchiveTargetId(rate.id))}
                  />
                </Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table>
        {rates.length === 0 ? (
          <EmptyState className="border-0" title="No interest rates configured" />
        ) : (
          list.visible.length === 0 && <NoMatchingRows status={list.status} hasSearch={list.search.trim() !== ""} />
        )}
      </Card>
      <ListCapNotice shown={rates.length} total={ratesTotal} />

      <ConfirmDialog
        isOpen={archiveTargetId !== null}
        title="Archive this interest rate?"
        message="New comparisons for this brand will have no active rate until a replacement is created."
        confirmLabel="Archive"
        onConfirm={() => void handleConfirmArchive()}
        onCancel={() => setArchiveTargetId(null)}
      />
    </div>
  );
}

function ResidualValueMatrixSection({ brands }: SectionProps) {
  const bandOptions = useMileageBandOptions();
  const mileageBandLabel = (band: string) => bandOptions.find((option) => option.value === band)?.label ?? band;
  const [entries, setEntries] = useState<ResidualValueMatrixEntry[]>([]);
  const [entriesTotal, setEntriesTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formValues, setFormValues] = useState<ResidualValueMatrixWritePayload>({
    brand: "",
    tenure_months: "",
    mileage_band: "",
    residual_value_ratio: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [archiveTargetId, setArchiveTargetId] = useState<number | null>(null);
  const list = useAdminListFilter(
    entries,
    (entry) => entry.is_active,
    (entry) => `${entry.brand_name} ${entry.tenure_months} ${mileageBandLabel(entry.mileage_band)}`,
  );

  useEffect(() => {
    fetchResidualValueMatrix()
      .then((data) => {
        setEntries(data);
        setEntriesTotal(listTotal(data));
      })
      .finally(() => setIsLoading(false));
  }, []);

  function openAdd() {
    setEditingId(null);
    setFormValues({ brand: "", tenure_months: "", mileage_band: "", residual_value_ratio: "" });
    setErrors({});
    setIsFormOpen(true);
  }

  function openEdit(entry: ResidualValueMatrixEntry) {
    setEditingId(entry.id);
    setFormValues({
      brand: entry.brand,
      tenure_months: entry.tenure_months,
      mileage_band: entry.mileage_band,
      residual_value_ratio: entry.residual_value_ratio,
    });
    setErrors({});
    setIsFormOpen(true);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setIsSubmitting(true);
    setErrors({});
    try {
      const saved =
        editingId === null
          ? await createResidualValueMatrixEntry(formValues)
          : await updateResidualValueMatrixEntry(editingId, {
              ...formValues,
              updated_at: entries.find((e) => e.id === editingId)?.updated_at,
            });
      setEntries((prev) =>
        editingId === null ? [...prev, saved] : prev.map((e) => (e.id === saved.id ? saved : e)),
      );
      setIsFormOpen(false);
    } catch (err: unknown) {
      setErrors(errorsFromCatch(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleConfirmArchive() {
    if (archiveTargetId === null) return;
    await archiveResidualValueMatrixEntry(archiveTargetId);
    setEntries((prev) => prev.map((e) => (e.id === archiveTargetId ? { ...e, is_active: false } : e)));
    setArchiveTargetId(null);
  }

  if (isLoading) return <LoadingSkeleton className="h-64 w-full" />;

  const brandOptions = formBrandOptions(brands, entries.find((e) => e.id === editingId)?.brand);

  return (
    <div className="flex flex-col gap-6">
      <SectionIntro
        title="Residual Overrides"
        purpose="Optional. Leave empty and the app estimates each car's residual from the baseline and adjustments."
      >
        A row here overrides the estimate for that brand, tenure and mileage band exactly. See the
        Residual Estimates section for what the app uses otherwise.
      </SectionIntro>
      {isFormOpen && (
        <Card>
          <form className="grid grid-cols-1 gap-4 md:grid-cols-2" onSubmit={handleSubmit}>
            <Select
              label="Brand"
              value={formValues.brand === "" ? "" : String(formValues.brand)}
              onChange={(e) =>
                setFormValues((prev) => ({
                  ...prev,
                  brand: e.target.value === "" ? "" : Number(e.target.value),
                }))
              }
              options={brandOptions}
              error={errors.brand}
            />
            <Input
              label="Tenure (months)"
              type="number"
              value={formValues.tenure_months === "" ? "" : String(formValues.tenure_months)}
              onChange={(e) =>
                setFormValues((prev) => ({
                  ...prev,
                  tenure_months: e.target.value === "" ? "" : Number(e.target.value),
                }))
              }
              error={errors.tenure_months}
            />
            <Select
              label="Mileage band"
              value={formValues.mileage_band}
              onChange={(e) => setFormValues((prev) => ({ ...prev, mileage_band: e.target.value }))}
              options={[{ value: "", label: "Select..." }, ...MILEAGE_BAND_OPTIONS]}
              error={errors.mileage_band}
            />
            <Input
              label="Residual value ratio (0-1)"
              value={formValues.residual_value_ratio}
              onChange={(e) =>
                setFormValues((prev) => ({ ...prev, residual_value_ratio: e.target.value }))
              }
              error={errors.residual_value_ratio}
            />
            {errors.detail && <p className="md:col-span-2 text-small text-danger-700">{errors.detail}</p>}
            {errors.non_field_errors && (
              <p className="md:col-span-2 text-small text-danger-700">{errors.non_field_errors}</p>
            )}
            <div className="flex gap-2 md:col-span-2">
              <Button type="submit" isLoading={isSubmitting}>
                {editingId === null ? "Create" : SAVE_LABEL}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setIsFormOpen(false)}>
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      )}

      <Card padding="none">
        <div className="p-4 sm:p-6">
          <AdminListToolbar
            searchLabel="Search residual overrides"
            {...list.toolbarProps}
            action={!isFormOpen && <Button onClick={openAdd}>Add Residual Override</Button>}
          />
        </div>
        <Table>
          <Table.Head>
            <Table.Row>
              <Table.HeaderCell>Brand</Table.HeaderCell>
              <Table.HeaderCell numeric>Tenure (mo)</Table.HeaderCell>
              <Table.HeaderCell>Mileage band</Table.HeaderCell>
              <Table.HeaderCell numeric>Residual (% of price)</Table.HeaderCell>
              <Table.HeaderCell>Status</Table.HeaderCell>
              <Table.HeaderCell>
                <span className="sr-only">Actions</span>
              </Table.HeaderCell>
            </Table.Row>
          </Table.Head>
          <Table.Body>
            {list.visible.map((entry) => (
              <Table.Row key={entry.id} className={entry.is_active ? undefined : ARCHIVED_ROW_CLASS}>
                <Table.Cell>{entry.brand_name}</Table.Cell>
                <Table.Cell numeric>{entry.tenure_months}</Table.Cell>
                {/* Run 3 fix batch 5 (F-18): the band in words, the same labels the compare screens use. */}
                <Table.Cell>{mileageBandLabel(entry.mileage_band)}</Table.Cell>
                {/* Redesign UI-6a: shown as a percentage (the API and the form keep the 0-1 ratio). */}
                <Table.Cell numeric>{formatRatioPercent(entry.residual_value_ratio)}</Table.Cell>
                <Table.Cell>
                  <StatusBadge isActive={entry.is_active} />
                </Table.Cell>
                <Table.Cell className="w-12 text-right">
                  <RowActionsMenu
                    label={`Actions for ${entry.brand_name} ${entry.tenure_months} months ${bandNameFromLabel(mileageBandLabel(entry.mileage_band))}`}
                    actions={editAndArchiveActions(entry.is_active, () => openEdit(entry), () => setArchiveTargetId(entry.id))}
                  />
                </Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table>
        {entries.length === 0 ? (
          <EmptyState className="border-0" title="No residual overrides - the estimates are used" />
        ) : (
          list.visible.length === 0 && <NoMatchingRows status={list.status} hasSearch={list.search.trim() !== ""} />
        )}
      </Card>
      <ListCapNotice shown={entries.length} total={entriesTotal} />

      <ConfirmDialog
        isOpen={archiveTargetId !== null}
        title="Archive this residual override?"
        message="GFV comparisons for this brand/tenure/mileage-band combination will go back to the app's estimate until another override is created."
        confirmLabel="Archive"
        onConfirm={() => void handleConfirmArchive()}
        onCancel={() => setArchiveTargetId(null)}
      />
    </div>
  );
}

// A light sequential tint for the baseline grid: a higher share of the price
// retained gets a slightly stronger indigo wash. Display only - the number is
// always printed in ink on top (at least 4.5:1 on every tint).
function residualTint(ratio: string): string {
  const value = Number(ratio);
  if (Number.isNaN(value)) return "";
  if (value >= 0.7) return "bg-primary-100";
  if (value >= 0.55) return "bg-primary-50";
  if (value >= 0.4) return "bg-primary-50/60";
  return "bg-primary-50/30";
}

// Audit batch 4: the tables the GFV residual estimator (apps.policy.residuals)
// reads - the baseline grid and the brand / powertrain adjustments. Read-only
// here (Django admin edits them); every figure is the API's value, shown as a
// percentage / points. All of it is a planning assumption, and says so.
function ResidualEstimatesSection() {
  const bandOptions = useMileageBandOptions();
  const [estimates, setEstimates] = useState<ResidualEstimatesResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchResidualEstimates()
      .then(setEstimates)
      .catch(() => setError("Could not load the residual estimates. Please try again."))
      .finally(() => setIsLoading(false));
  }, []);

  if (isLoading) return <LoadingSkeleton className="h-64 w-full" />;
  if (error || !estimates) return <EmptyState title="Residual estimates unavailable" description={error ?? ""} />;

  const tenures = Array.from(new Set(estimates.baselines.map((row) => row.tenure_months))).sort((a, b) => a - b);
  const adjustmentNotes = splitSourceNotes(estimates.adjustments);

  return (
    <div className="flex flex-col gap-6">
      <SectionIntro
        title="Residual Estimates"
        purpose="Each car's GFV residual = baseline for its tenure and mileage band, plus its brand's adjustment, plus its powertrain's adjustment. Edit in Django admin."
      >
        These are planning assumptions, not market data - real GFV residuals are set by the
        lender. A new brand or powertrain with no adjustment row simply gets 0 points. A row in
        Residual Overrides wins over all of this.
      </SectionIntro>

      <Card padding="none">
        <div className="p-4 pb-0 sm:px-6">
          <h3 className="text-h3 font-semibold text-ink">Baseline: share of price retained</h3>
          <p className="text-caption text-ink-muted">
            By tenure and annual-mileage band, as a percentage of the vehicle's price. A stronger tint
            means more of the price is retained.
          </p>
        </div>
        <Table>
          <Table.Head>
            <Table.Row>
              <Table.HeaderCell numeric>Tenure (mo)</Table.HeaderCell>
              {/* The band names from the API's list (no km figures written here). */}
              {bandOptions.map((band) => (
                <Table.HeaderCell key={band.value} numeric>
                  {bandNameFromLabel(band.label)}
                </Table.HeaderCell>
              ))}
            </Table.Row>
          </Table.Head>
          <Table.Body>
            {tenures.map((tenure) => (
              <Table.Row key={tenure}>
                <Table.Cell numeric>{tenure}</Table.Cell>
                {bandOptions.map((band) => {
                  const row = estimates.baselines.find(
                    (item) => item.tenure_months === tenure && item.mileage_band === band.value,
                  );
                  return (
                    <Table.Cell key={band.value} numeric className={row ? residualTint(row.ratio) : undefined}>
                      {row ? formatRatioPercent(row.ratio) : "-"}
                    </Table.Cell>
                  );
                })}
              </Table.Row>
            ))}
          </Table.Body>
        </Table>
        {estimates.baselines.length === 0 && (
          <EmptyState className="border-0" title="No baseline configured - GFV cannot be estimated" />
        )}
        <div className="px-4 pb-4 sm:px-6">
          <SourceNotes rows={estimates.baselines} />
        </div>
      </Card>

      <Card padding="none">
        <div className="p-4 pb-0 sm:px-6">
          <h3 className="text-h3 font-semibold text-ink">Adjustments by brand and powertrain</h3>
          <p className="text-caption text-ink-muted">
            In percentage points added to the baseline (+6.00 pts takes 50.00% to 56.00%).
          </p>
        </div>
        <Table>
          <Table.Head>
            <Table.Row>
              <Table.HeaderCell>Applies to</Table.HeaderCell>
              <Table.HeaderCell>Kind</Table.HeaderCell>
              <Table.HeaderCell numeric>Points</Table.HeaderCell>
              <Table.HeaderCell>Note</Table.HeaderCell>
              <Table.HeaderCell>Effective from</Table.HeaderCell>
            </Table.Row>
          </Table.Head>
          <Table.Body>
            {estimates.adjustments.map((row) => (
              <Table.Row key={row.id}>
                <Table.Cell>{row.brand_name ?? row.powertrain_label}</Table.Cell>
                <Table.Cell>{row.brand_name ? "Brand" : "Powertrain"}</Table.Cell>
                <Table.Cell numeric>{formatRatioPoints(row.delta_points)}</Table.Cell>
                {/* FX-3 (X13): only what this row's source adds; the shared source is under the table. */}
                <Table.Cell className="min-w-48 text-caption text-ink-muted">{adjustmentNotes.extra(row) || "-"}</Table.Cell>
                <Table.Cell>{formatAdminDate(row.effective_from)}</Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table>
        {estimates.adjustments.length === 0 && (
          <EmptyState className="border-0" title="No adjustments configured - every car gets the baseline" />
        )}
        <div className="px-4 pb-4 sm:px-6">
          <SourceNotes rows={estimates.adjustments} showExtras={false} />
        </div>
      </Card>
    </div>
  );
}

function MCDAWeightsSection() {
  const [weights, setWeights] = useState<MCDACriteriaWeight[]>([]);
  const [draft, setDraft] = useState<Record<MCDACriterion, string>>({
    upfront_cash_preservation: "0",
    maintenance_protection: "0",
    ownership_equity: "0",
  });
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    fetchMCDAWeights()
      .then((data) => {
        setWeights(data);
        const next = { ...draft };
        data.forEach((w) => {
          next[w.criterion] = w.default_weight;
        });
        setDraft(next);
      })
      .finally(() => setIsLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runningSum = (Object.values(draft) as string[]).reduce(
    (sum, value) => sum + (Number(value) || 0),
    0,
  );

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      const payload = (Object.keys(draft) as MCDACriterion[]).map((criterion) => ({
        criterion,
        default_weight: draft[criterion],
      }));
      const updated = await updateMCDAWeights(payload);
      setWeights(updated);
    } catch (err: unknown) {
      setError(
        (axios.isAxiosError(err) && parseApiErrorMessage(err.response?.data)) || GENERIC_ERROR,
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  if (isLoading) return <LoadingSkeleton className="h-48 w-full" />;

  return (
    <div className="flex flex-col gap-6">
      <SectionIntro
        title="Default Priority Weights"
        purpose="Reference defaults. A buyer's own three priority ratings decide the recommendation; these defaults are not applied to scoring yet."
      />
      <Card>
        <p className="text-small text-ink-muted">
          Must sum to 1.0 (100%) - the server re-validates this regardless of the running total
          shown below. Each weight is entered as a decimal (0.3400 = 34%).
        </p>
        <form className="mt-4 flex max-w-md flex-col gap-4" onSubmit={handleSubmit}>
          {/* FX-3 (X13): each weight also shown as a percentage (display only; the
              decimal typed here is what is sent). */}
          {(Object.keys(MCDA_CRITERION_LABELS) as MCDACriterion[]).map((criterion) => (
            <div key={criterion} className="flex items-end gap-3">
              <div className="min-w-0 flex-1">
                <Input
                  label={MCDA_CRITERION_LABELS[criterion]}
                  value={draft[criterion]}
                  onChange={(e) => setDraft((prev) => ({ ...prev, [criterion]: e.target.value }))}
                />
              </div>
              <span className="w-16 shrink-0 pb-2.5 text-right text-small font-semibold tabular-nums text-ink">
                {formatWeightPercent(draft[criterion])}
              </span>
            </div>
          ))}
          <p
            className={
              Math.abs(runningSum - 1) < 0.0001 ? "text-small text-positive-700" : "text-small text-warning-700"
            }
          >
            Running sum: {formatWeightPercent(runningSum)}
          </p>
          {error && <p className="text-small text-danger-700">{error}</p>}
          <div>
            <Button type="submit" isLoading={isSubmitting}>
              Save Weights
            </Button>
          </div>
        </form>

        {weights.length > 0 && (
          <p className="mt-4 text-caption text-ink-muted">
            Last updated: {formatAdminDateTime(weights[0].updated_at)}
          </p>
        )}
      </Card>
    </div>
  );
}

// Audit batch 2: road tax, insurance and maintenance are derived per vehicle
// by one engine (apps.policy.operating_costs) from three admin-managed rate
// tables. This section only SHOWS them, with where each rate came from - edits
// are made in Django admin (inline editing is deferred). Every figure is the
// API's value, shown with its unit.
// FX-3 (X13): the source is said once under its table - the part every row
// shares, then (unless the table has its own Note column) what any row adds.
function SourceNotes({ rows, showExtras = true }: { rows: { source_note: string }[]; showExtras?: boolean }) {
  const { common, extra } = splitSourceNotes(rows);
  const extras = showExtras ? Array.from(new Set(rows.map(extra).filter(Boolean))) : [];
  if (common.length === 0) return null;
  return (
    <ul className="mt-3 flex flex-col gap-1 text-caption text-ink-muted">
      {common.map((note) => (
        <li key={note}>Source: {note}</li>
      ))}
      {extras.map((note) => (
        <li key={`extra-${note}`}>{note}</li>
      ))}
    </ul>
  );
}

// One collapsible group of a read-only section (a native <details>: its table
// stays in the page while folded). Its table scrolls inside its own container
// on a phone.
function CollapsibleGroup({
  title,
  badge,
  defaultOpen = false,
  children,
}: {
  title: string;
  badge?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <details className="group rounded-card border border-border bg-surface shadow-card" open={defaultOpen || undefined}>
      <summary
        className={cn(
          "flex cursor-pointer list-none items-center gap-2 rounded-card px-4 py-3 sm:px-6 [&::-webkit-details-marker]:hidden",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary-500",
        )}
      >
        <h3 className="text-h3 font-semibold text-ink">{title}</h3>
        {badge}
        <ChevronDown
          className="ml-auto h-5 w-5 shrink-0 text-ink-muted transition-transform group-open:rotate-180"
          aria-hidden="true"
        />
      </summary>
      <div className="border-t border-border">{children}</div>
    </details>
  );
}

function CcBandsTable({
  title,
  description,
  bands,
  archived = false,
  defaultOpen = false,
}: {
  title: string;
  description: string;
  bands: RoadTaxCcBandRow[];
  archived?: boolean;
  defaultOpen?: boolean;
}) {
  return (
    <CollapsibleGroup title={title} badge={archived && <Badge tone="neutral">Archived</Badge>} defaultOpen={defaultOpen}>
      <div className="px-4 pt-3 sm:px-6">
        <InfoExpander summary="About this table">{description}</InfoExpander>
      </div>
      <Table>
        <Table.Head>
          <Table.Row>
            <Table.HeaderCell numeric>From cc</Table.HeaderCell>
            <Table.HeaderCell numeric>To cc</Table.HeaderCell>
            <Table.HeaderCell numeric>Base</Table.HeaderCell>
            <Table.HeaderCell>Rate above threshold</Table.HeaderCell>
            <Table.HeaderCell>Effective from</Table.HeaderCell>
          </Table.Row>
        </Table.Head>
        <Table.Body>
          {bands.map((band) => (
            <Table.Row key={band.id}>
              <Table.Cell numeric>{band.min_cc}</Table.Cell>
              <Table.Cell numeric>{band.max_cc}</Table.Cell>
              <Table.Cell numeric>{formatCurrency(band.base_amount)}</Table.Cell>
              <Table.Cell>
                {band.threshold_cc > 0
                  ? `${formatCurrency(band.per_cc_rate)} per cc above ${band.threshold_cc}`
                  : "Flat"}
              </Table.Cell>
              <Table.Cell>{formatAdminDate(band.effective_from)}</Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
      <div className="px-4 pb-4 sm:px-6">
        <SourceNotes rows={bands} />
      </div>
    </CollapsibleGroup>
  );
}

function OperatingCostsSection() {
  const [costs, setCosts] = useState<OperatingCostsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchOperatingCosts()
      .then(setCosts)
      .catch(() => setError("Could not load the operating cost rates. Please try again."))
      .finally(() => setIsLoading(false));
  }, []);

  if (isLoading) return <LoadingSkeleton className="h-64 w-full" />;
  if (error || !costs) return <EmptyState title="Operating costs unavailable" description={error ?? ""} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="mb-2">
        <SectionIntro
          title="Operating Costs"
          purpose="Road tax follows JPJ; insurance and maintenance are percentage estimates. Edit in Django admin."
        >
          One engine derives all three figures for every vehicle from its own registration class,
          powertrain, engine capacity and price - nothing is keyed in per car. Estimates are for
          Peninsular Malaysia, private car. Insurance is shown before the buyer's No-Claim Discount,
          which each buyer sets in their Financial Profile (it never changes a subscription fee).
        </SectionIntro>
      </div>

      <CcBandsTable
        title="Road tax by engine capacity (cc) - saloon"
        description="Saloon-registered cars (sedans, hatchbacks, coupes by default), petrol or diesel, including hybrids and plug-in hybrids. Tax = base + (cc - threshold) x rate per cc."
        bands={costs.road_tax_cc_bands.filter((band) => band.vehicle_class === "saloon")}
        defaultOpen
      />
      <CcBandsTable
        title="Road tax by engine capacity (cc) - non-saloon"
        description="Non-saloon-registered cars (SUVs, MPVs, pick-ups, vans, crossovers by default), petrol or diesel. The class on the car's registration card (VOC) decides."
        bands={costs.road_tax_cc_bands.filter((band) => band.vehicle_class === "non_saloon")}
      />

      <CollapsibleGroup title="Battery-electric road tax by motor power (kW)">
        <div className="px-4 pt-3 sm:px-6">
          <InfoExpander summary="About this table">
            Battery electric only. Tax = base up to the "base until" kW, then the increment for each
            further 10 kW block (rounded up).
          </InfoExpander>
        </div>
        <Table>
          <Table.Head>
            <Table.Row>
              <Table.HeaderCell>Group</Table.HeaderCell>
              <Table.HeaderCell>Motor power</Table.HeaderCell>
              <Table.HeaderCell numeric>Base</Table.HeaderCell>
              <Table.HeaderCell numeric>Base until</Table.HeaderCell>
              <Table.HeaderCell numeric>Per extra 10 kW</Table.HeaderCell>
              <Table.HeaderCell>Effective from</Table.HeaderCell>
            </Table.Row>
          </Table.Head>
          <Table.Body>
            {costs.ev_road_tax_groups.map((group) => (
              <Table.Row key={group.id}>
                <Table.Cell>{group.label}</Table.Cell>
                {/* FX-3 (X13): one readable range from the API's bounds (was "910.100" / "1010.000"). */}
                <Table.Cell className="whitespace-nowrap">{formatKwRange(group.min_kw, group.max_kw)}</Table.Cell>
                <Table.Cell numeric>{formatCurrency(group.base_amount)}</Table.Cell>
                <Table.Cell numeric>
                  {group.base_until_kw === null ? "Fixed amount" : `${formatKw(group.base_until_kw)} kW`}
                </Table.Cell>
                <Table.Cell numeric>
                  {group.base_until_kw === null ? "-" : formatCurrency(group.increment_per_10kw)}
                </Table.Cell>
                <Table.Cell>{formatAdminDate(group.effective_from)}</Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table>
        <div className="px-4 pb-4 sm:px-6">
          <SourceNotes rows={costs.ev_road_tax_groups} />
        </div>
      </CollapsibleGroup>

      <CollapsibleGroup title="Insurance and maintenance estimates">
        <div className="px-4 pt-3 sm:px-6">
          <InfoExpander summary="About this table">
            Percent of the vehicle's price per year, by powertrain. Maintenance never falls below the floor
            or rises above the cap - both planning assumptions, not tariffs.
          </InfoExpander>
        </div>
        <Table>
          <Table.Head>
            <Table.Row>
              <Table.HeaderCell>Powertrain</Table.HeaderCell>
              <Table.HeaderCell numeric>Insurance (% of price)</Table.HeaderCell>
              <Table.HeaderCell numeric>Maintenance (% of price)</Table.HeaderCell>
              <Table.HeaderCell numeric>Maintenance floor</Table.HeaderCell>
              <Table.HeaderCell numeric>Maintenance cap</Table.HeaderCell>
              <Table.HeaderCell>Effective from</Table.HeaderCell>
            </Table.Row>
          </Table.Head>
          <Table.Body>
            {costs.cost_rates.map((rate) => (
              <Table.Row key={rate.id}>
                <Table.Cell>{rate.powertrain_label}</Table.Cell>
                {/* Redesign UI-6a: 2 dp with its unit (the API keeps 4 dp). */}
                <Table.Cell numeric>{formatPercent(rate.insurance_rate_percent)}</Table.Cell>
                <Table.Cell numeric>{formatPercent(rate.maintenance_rate_percent)}</Table.Cell>
                <Table.Cell numeric>{formatCurrency(rate.maintenance_floor_annual)}</Table.Cell>
                <Table.Cell numeric>
                  {rate.maintenance_cap_annual === null ? "No cap" : formatCurrency(rate.maintenance_cap_annual)}
                </Table.Cell>
                <Table.Cell>{formatAdminDate(rate.effective_from)}</Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table>
        <div className="px-4 pb-4 sm:px-6">
          <SourceNotes rows={costs.cost_rates} />
        </div>
      </CollapsibleGroup>

      {costs.archived_diesel_cc_bands.length > 0 && (
        <CcBandsTable
          title="Archived: old diesel schedule (not used)"
          description="Read-only record. Diesel now uses the same table as petrol for its class; these rows came from a single 2006 source and are kept only for the audit trail."
          bands={costs.archived_diesel_cc_bands}
          archived
        />
      )}
    </div>
  );
}

// Audit batch 5: the assumptions every Subscription fee is estimated from
// (apps.policy.subscription_pricing). Read-only here - Django admin edits them;
// every value is shown as the API returned it, with its unit, and is a planning
// assumption, not provider data.
function SubscriptionEstimatesSection() {
  const bandOptions = useMileageBandOptions();
  const [estimates, setEstimates] = useState<SubscriptionEstimatesResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSubscriptionEstimates()
      .then(setEstimates)
      .catch(() => setError("Could not load the subscription estimates. Please try again."))
      .finally(() => setIsLoading(false));
  }, []);

  if (isLoading) return <LoadingSkeleton className="h-64 w-full" />;
  if (error || !estimates) return <EmptyState title="Subscription estimates unavailable" description={error ?? ""} />;

  return (
    <div className="flex flex-col gap-6">
      <SectionIntro
        title="Subscription Estimates"
        purpose="Fee = (depreciation + funding + road tax, insurance and maintenance) per month, plus the margin. Edit in Django admin."
      >
        Depreciation uses the car's own residual (see Residual Estimates); a plan in Provider Quote
        Overrides wins over the estimate. All of these are planning assumptions, not provider data -
        real subscription terms vary by provider.
      </SectionIntro>

      <Card padding="none">
        <Table>
          <Table.Head>
            <Table.Row>
              <Table.HeaderCell numeric>Shortest (months)</Table.HeaderCell>
              <Table.HeaderCell numeric>Longest (months)</Table.HeaderCell>
              <Table.HeaderCell numeric>Funding rate (p.a.)</Table.HeaderCell>
              <Table.HeaderCell numeric>Margin</Table.HeaderCell>
              <Table.HeaderCell numeric>Deposit (months of fee)</Table.HeaderCell>
              <Table.HeaderCell>Effective from</Table.HeaderCell>
            </Table.Row>
          </Table.Head>
          <Table.Body>
            {estimates.policies.map((policy) => (
              <Table.Row key={policy.id}>
                <Table.Cell numeric>{policy.min_tenure_months}</Table.Cell>
                <Table.Cell numeric>{policy.max_tenure_months}</Table.Cell>
                {/* Run 3 fix batch 5 (F-18): 2 dp percentages and km with their units (display only). */}
                <Table.Cell numeric>{formatPercent(policy.funding_rate_percent)}</Table.Cell>
                <Table.Cell numeric>{formatPercent(policy.margin_percent)}</Table.Cell>
                <Table.Cell numeric>{trimNumber(policy.deposit_months)}</Table.Cell>
                <Table.Cell>{formatAdminDate(policy.effective_from)}</Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table>
        {estimates.policies.length === 0 && (
          <EmptyState className="border-0" title="No subscription policy configured - Subscription cannot be estimated" />
        )}
        <div className="px-4 pb-4 sm:px-6">
          <SourceNotes rows={estimates.policies} />
        </div>
      </Card>

      {/* Run 3 fix batch 6: the mileage bands and the km a year each one includes - the
          one definition, served by the API (labels and figures are never written here). */}
      <Card>
        <h3 className="text-small font-semibold text-ink">Mileage bands and included km</h3>
        <ul className="mt-2 flex flex-col gap-1 text-small text-ink">
          {bandOptions.map((band) => (
            <li key={band.value}>
              {band.label}
              {band.included_km_per_year != null && (
                <span className="text-ink-muted"> - includes {formatKmPerYear(band.included_km_per_year)}</span>
              )}
            </li>
          ))}
        </ul>
        <p className="mt-2 text-caption text-ink-muted">
          Each band's limit is also the km a year a Subscription in that band includes; the very high
          band is modelled and sold up to its own limit. Planning assumptions - edit them in Django admin.
        </p>
      </Card>
    </div>
  );
}

function SubscriptionPlansSection({ vehicles }: { vehicles: AdminVehicle[] }) {
  const [plans, setPlans] = useState<SubscriptionPlan[]>([]);
  const [plansTotal, setPlansTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formValues, setFormValues] = useState<SubscriptionPlanWritePayload>({
    vehicle: "",
    fee_monthly: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [archiveTargetId, setArchiveTargetId] = useState<number | null>(null);
  const list = useAdminListFilter(plans, (plan) => plan.is_active, (plan) => plan.vehicle_label);

  useEffect(() => {
    fetchSubscriptionPlans()
      .then((data) => {
        setPlans(data);
        setPlansTotal(listTotal(data));
      })
      .finally(() => setIsLoading(false));
  }, []);

  function openAdd() {
    setEditingId(null);
    setFormValues({
      vehicle: "",
      fee_monthly: "",
    });
    setErrors({});
    setIsFormOpen(true);
  }

  function openEdit(plan: SubscriptionPlan) {
    setEditingId(plan.id);
    setFormValues({
      vehicle: plan.vehicle,
      fee_monthly: plan.fee_monthly,
    });
    setErrors({});
    setIsFormOpen(true);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setIsSubmitting(true);
    setErrors({});
    try {
      const saved =
        editingId === null
          ? await createSubscriptionPlan(formValues)
          : await updateSubscriptionPlan(editingId, {
              ...formValues,
              updated_at: plans.find((p) => p.id === editingId)?.updated_at,
            });
      setPlans((prev) =>
        editingId === null ? [...prev, saved] : prev.map((p) => (p.id === saved.id ? saved : p)),
      );
      setIsFormOpen(false);
    } catch (err: unknown) {
      setErrors(errorsFromCatch(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleConfirmArchive() {
    if (archiveTargetId === null) return;
    await archiveSubscriptionPlan(archiveTargetId);
    setPlans((prev) => prev.map((p) => (p.id === archiveTargetId ? { ...p, is_active: false } : p)));
    setArchiveTargetId(null);
  }

  if (isLoading) return <LoadingSkeleton className="h-64 w-full" />;

  // Run 3 fix batch 4 (F-13): a quote can only be added for an active car; the
  // row being edited keeps its own (possibly archived) car selectable, the same
  // rule formBrandOptions uses for brands. The server enforces it too.
  const editingVehicleId = plans.find((p) => p.id === editingId)?.vehicle;
  const vehicleOptions = [
    { value: "", label: "Select a vehicle..." },
    ...vehicles
      .filter((v) => v.is_active || v.id === editingVehicleId)
      .map((v) => ({
        value: String(v.id),
        label: `${v.brand_name} ${v.name} ${v.trim}${v.is_active ? "" : " (archived)"}`,
      })),
  ];

  return (
    <div className="flex flex-col gap-6">
      <SectionIntro
        title="Provider Quote Overrides"
        purpose="Optional. Leave a car without a plan and the app estimates its subscription fee from depreciation, funding, running costs and a margin. Add a plan only when you have a real provider quote."
      >
        A quoted fee is used exactly and does not change with tenure or mileage band. See
        Subscription Estimates for the assumptions the estimate uses.
      </SectionIntro>
      {isFormOpen && (
        <Card>
          <form className="grid grid-cols-1 gap-4 md:grid-cols-2" onSubmit={handleSubmit}>
            <Select
              label="Vehicle"
              value={formValues.vehicle === "" ? "" : String(formValues.vehicle)}
              onChange={(e) =>
                setFormValues((prev) => ({
                  ...prev,
                  vehicle: e.target.value === "" ? "" : Number(e.target.value),
                }))
              }
              options={vehicleOptions}
              error={errors.vehicle}
            />
            <Input
              label="Monthly fee (RM)"
              value={formValues.fee_monthly}
              onChange={(e) => setFormValues((prev) => ({ ...prev, fee_monthly: e.target.value }))}
              error={errors.fee_monthly}
            />
            {errors.detail && <p className="md:col-span-2 text-small text-danger-700">{errors.detail}</p>}
            <div className="flex gap-2 md:col-span-2">
              <Button type="submit" isLoading={isSubmitting}>
                {editingId === null ? "Create" : SAVE_LABEL}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setIsFormOpen(false)}>
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      )}

      <Card padding="none">
        <div className="p-4 sm:p-6">
          <AdminListToolbar
            searchLabel="Search provider quotes"
            {...list.toolbarProps}
            action={!isFormOpen && <Button onClick={openAdd}>Add Subscription Plan</Button>}
          />
        </div>
        <Table>
          <Table.Head>
            <Table.Row>
              <Table.HeaderCell>Vehicle</Table.HeaderCell>
              <Table.HeaderCell numeric>Monthly fee</Table.HeaderCell>
              <Table.HeaderCell>Status</Table.HeaderCell>
              <Table.HeaderCell>
                <span className="sr-only">Actions</span>
              </Table.HeaderCell>
            </Table.Row>
          </Table.Head>
          <Table.Body>
            {list.visible.map((plan) => (
              <Table.Row key={plan.id} className={plan.is_active ? undefined : ARCHIVED_ROW_CLASS}>
                <Table.Cell>{plan.vehicle_label}</Table.Cell>
                <Table.Cell numeric>{formatCurrency(plan.fee_monthly)}</Table.Cell>
                <Table.Cell>
                  <StatusBadge isActive={plan.is_active} />
                </Table.Cell>
                <Table.Cell className="w-12 text-right">
                  <RowActionsMenu
                    label={`Actions for ${plan.vehicle_label} quote`}
                    actions={editAndArchiveActions(plan.is_active, () => openEdit(plan), () => setArchiveTargetId(plan.id))}
                  />
                </Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table>
        {plans.length === 0 ? (
          <EmptyState className="border-0" title="No provider quotes - every fee is estimated" />
        ) : (
          list.visible.length === 0 && <NoMatchingRows status={list.status} hasSearch={list.search.trim() !== ""} />
        )}
      </Card>
      <ListCapNotice shown={plans.length} total={plansTotal} />

      <ConfirmDialog
        isOpen={archiveTargetId !== null}
        title="Archive this subscription plan?"
        message="This vehicle's subscription fee will go back to the app's estimate until another quote is entered."
        confirmLabel="Archive"
        onConfirm={() => void handleConfirmArchive()}
        onCancel={() => setArchiveTargetId(null)}
      />
    </div>
  );
}

function ContractPenaltyRulesSection({ brands }: SectionProps) {
  const [rules, setRules] = useState<ContractPenaltyRule[]>([]);
  const [rulesTotal, setRulesTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formValues, setFormValues] = useState<ContractPenaltyRuleWritePayload>({
    brand: null,
    excess_mileage_charge_per_km: "",
    early_termination_months: "",
    wear_tear_tolerance_description: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [archiveTargetId, setArchiveTargetId] = useState<number | null>(null);
  const ruleName = (rule: ContractPenaltyRule) => rule.brand_name ?? "Default (all brands)";
  const list = useAdminListFilter(
    rules,
    (rule) => rule.is_active,
    (rule) => `${ruleName(rule)} ${rule.wear_tear_tolerance_description}`,
  );

  useEffect(() => {
    fetchContractPenaltyRules()
      .then((data) => {
        setRules(data);
        setRulesTotal(listTotal(data));
      })
      .finally(() => setIsLoading(false));
  }, []);

  function openAdd() {
    setEditingId(null);
    setFormValues({
      brand: null,
      excess_mileage_charge_per_km: "",
      early_termination_months: "",
      wear_tear_tolerance_description: "",
    });
    setErrors({});
    setIsFormOpen(true);
  }

  function openEdit(rule: ContractPenaltyRule) {
    setEditingId(rule.id);
    setFormValues({
      brand: rule.brand,
      excess_mileage_charge_per_km: rule.excess_mileage_charge_per_km,
      early_termination_months: rule.early_termination_months ?? "",
      wear_tear_tolerance_description: rule.wear_tear_tolerance_description,
    });
    setErrors({});
    setIsFormOpen(true);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setIsSubmitting(true);
    setErrors({});
    try {
      const saved =
        editingId === null
          ? await createContractPenaltyRule(formValues)
          : await updateContractPenaltyRule(editingId, {
              ...formValues,
              updated_at: rules.find((r) => r.id === editingId)?.updated_at,
            });
      setRules((prev) =>
        editingId === null ? [...prev, saved] : prev.map((r) => (r.id === saved.id ? saved : r)),
      );
      setIsFormOpen(false);
    } catch (err: unknown) {
      setErrors(errorsFromCatch(err));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleConfirmArchive() {
    if (archiveTargetId === null) return;
    await archiveContractPenaltyRule(archiveTargetId);
    setRules((prev) => prev.map((r) => (r.id === archiveTargetId ? { ...r, is_active: false } : r)));
    setArchiveTargetId(null);
  }

  if (isLoading) return <LoadingSkeleton className="h-64 w-full" />;

  // "Default rule (all brands)" replaces the usual "Select a brand..." placeholder:
  // an empty brand IS the default rule every brand without its own row falls back to.
  const brandOptions = formBrandOptions(brands, rules.find((r) => r.id === editingId)?.brand).map((option) =>
    option.value === "" ? { value: "", label: "Default rule (all brands)" } : option,
  );

  return (
    <div className="flex flex-col gap-6">
      <SectionIntro
        title="Contract Penalty Rules"
        purpose="A brand with no rule of its own uses the default rule, so a new brand needs nothing keyed. These are planning estimates; typical terms vary by provider."
      >
        The subscription early-return fee is a number of months of the subscription fee shown on
        each report (or the fees left, whichever is lower), never a stored ringgit amount - do not
        type fee amounts into the text either. Leave it empty on a brand rule to use the default's
        months. Settling a Hire Purchase loan early has no penalty (reducing-balance method). Wear
        and tear is a checklist note only, not a cost.
      </SectionIntro>
      {isFormOpen && (
        <Card>
          <form className="grid grid-cols-1 gap-4 md:grid-cols-2" onSubmit={handleSubmit}>
            <Select
              label="Brand"
              value={formValues.brand === null ? "" : String(formValues.brand)}
              onChange={(e) =>
                setFormValues((prev) => ({
                  ...prev,
                  brand: e.target.value === "" ? null : Number(e.target.value),
                }))
              }
              options={brandOptions}
              error={errors.brand}
            />
            <Input
              label="Excess mileage charge (RM/km)"
              value={formValues.excess_mileage_charge_per_km}
              onChange={(e) =>
                setFormValues((prev) => ({ ...prev, excess_mileage_charge_per_km: e.target.value }))
              }
              error={errors.excess_mileage_charge_per_km}
            />
            <Input
              label="Subscription early-return fee (months of fee)"
              value={formValues.early_termination_months}
              onChange={(e) =>
                setFormValues((prev) => ({ ...prev, early_termination_months: e.target.value }))
              }
              error={errors.early_termination_months}
            />
            <div className="flex flex-col gap-1.5 md:col-span-2">
              <label htmlFor="wear-tear-description" className="text-small font-medium text-ink">
                Wear &amp; tear tolerance description
              </label>
              <textarea
                id="wear-tear-description"
                rows={3}
                className="rounded-md border border-border bg-surface px-3 py-2 text-body text-ink focus:outline-none focus:ring-2 focus:ring-primary-500"
                value={formValues.wear_tear_tolerance_description}
                onChange={(e) =>
                  setFormValues((prev) => ({
                    ...prev,
                    wear_tear_tolerance_description: e.target.value,
                  }))
                }
              />
              {errors.wear_tear_tolerance_description && (
                <p className="text-small text-danger-700">{errors.wear_tear_tolerance_description}</p>
              )}
            </div>
            {errors.detail && <p className="md:col-span-2 text-small text-danger-700">{errors.detail}</p>}
            <div className="flex gap-2 md:col-span-2">
              <Button type="submit" isLoading={isSubmitting}>
                {editingId === null ? "Create" : SAVE_LABEL}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setIsFormOpen(false)}>
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      )}

      <Card padding="none">
        <div className="p-4 sm:p-6">
          <AdminListToolbar
            searchLabel="Search contract rules"
            {...list.toolbarProps}
            action={!isFormOpen && <Button onClick={openAdd}>Add Contract Penalty Rule</Button>}
          />
        </div>
        <Table>
          <Table.Head>
            <Table.Row>
              <Table.HeaderCell>Brand</Table.HeaderCell>
              <Table.HeaderCell numeric>Excess mileage (RM/km)</Table.HeaderCell>
              <Table.HeaderCell numeric>Subscription early-return fee (months of fee)</Table.HeaderCell>
              <Table.HeaderCell>Wear and tear terms</Table.HeaderCell>
              <Table.HeaderCell>Status</Table.HeaderCell>
              <Table.HeaderCell>
                <span className="sr-only">Actions</span>
              </Table.HeaderCell>
            </Table.Row>
          </Table.Head>
          <Table.Body>
            {list.visible.map((rule) => (
              <Table.Row key={rule.id} className={rule.is_active ? undefined : ARCHIVED_ROW_CLASS}>
                <Table.Cell>{ruleName(rule)}</Table.Cell>
                <Table.Cell numeric>{formatPlainAmount(rule.excess_mileage_charge_per_km)}</Table.Cell>
                <Table.Cell numeric>{rule.early_termination_months ?? "Default's"}</Table.Cell>
                {/* The rule's full text, complete, one click away. */}
                <Table.Cell className="min-w-[12rem] max-w-md">
                  {rule.wear_tear_tolerance_description ? (
                    <InfoExpander summary="Read the terms">
                      <span className="whitespace-pre-line">{rule.wear_tear_tolerance_description}</span>
                    </InfoExpander>
                  ) : (
                    <span className="text-ink-muted">-</span>
                  )}
                </Table.Cell>
                <Table.Cell>
                  <StatusBadge isActive={rule.is_active} />
                </Table.Cell>
                <Table.Cell className="w-12 text-right">
                  <RowActionsMenu
                    label={`Actions for ${ruleName(rule)} rule`}
                    actions={editAndArchiveActions(rule.is_active, () => openEdit(rule), () => setArchiveTargetId(rule.id))}
                  />
                </Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table>
        {rules.length === 0 ? (
          <EmptyState className="border-0" title="No contract penalty rules configured" />
        ) : (
          list.visible.length === 0 && <NoMatchingRows status={list.status} hasSearch={list.search.trim() !== ""} />
        )}
      </Card>
      <ListCapNotice shown={rules.length} total={rulesTotal} />

      <ConfirmDialog
        isOpen={archiveTargetId !== null}
        title="Archive this contract penalty rule?"
        message="Reports for this brand (or, for the default rule, for every brand without its own rule) will have no contract terms until a replacement is created."
        confirmLabel="Archive"
        onConfirm={() => void handleConfirmArchive()}
        onCancel={() => setArchiveTargetId(null)}
      />
    </div>
  );
}

// The 8 sections, in their order, with the labels the page has always used.
const SECTIONS: { value: string; label: string; icon: ReactNode }[] = [
  { value: "interest-rates", label: "Interest Rates", icon: <Percent className="h-4 w-4" /> },
  { value: "residual-value-matrix", label: "Residual Overrides", icon: <SlidersHorizontal className="h-4 w-4" /> },
  { value: "residual-estimates", label: "Residual Estimates", icon: <TrendingDown className="h-4 w-4" /> },
  { value: "mcda-weights", label: "Default Priority Weights", icon: <Scale className="h-4 w-4" /> },
  { value: "operating-costs", label: "Operating Costs", icon: <Fuel className="h-4 w-4" /> },
  { value: "subscription-plans", label: "Provider Quote Overrides", icon: <Receipt className="h-4 w-4" /> },
  { value: "subscription-estimates", label: "Subscription Estimates", icon: <Calculator className="h-4 w-4" /> },
  { value: "contract-penalty-rules", label: "Contract Penalty Rules", icon: <FileText className="h-4 w-4" /> },
];

export function AdminPolicyPage() {
  useDocumentTitle("Policy Configuration");
  const [tab, setTab] = useState("interest-rates");
  const [brands, setBrands] = useState<AdminBrand[]>([]);
  const [vehicles, setVehicles] = useState<AdminVehicle[]>([]);
  const [isLoadingLookups, setIsLoadingLookups] = useState(true);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    setIsLoadingLookups(true);
    setLookupError(null);
    Promise.all([fetchAdminBrands(), fetchAdminVehicles()])
      .then(([brandData, vehicleData]) => {
        setBrands(brandData);
        setVehicles(vehicleData);
      })
      .catch(() => setLookupError("Could not load brand/vehicle reference data. Please try again."))
      .finally(() => setIsLoadingLookups(false));
  }, [reloadKey]);

  return (
    <div className="mx-auto max-w-7xl px-4 pb-16 pt-8 sm:pt-10">
      <PageHeader
        title="Policy configuration"
        subtitle="Rates, residuals, costs and contract rules the calculations use."
      />

      {isLoadingLookups && <LoadingSkeleton className="mt-6 h-64 w-full" />}
      {!isLoadingLookups && lookupError && (
        <div role="alert" className="mt-6">
          <EmptyState
            title="Configuration unavailable"
            description={lookupError}
            action={<Button onClick={() => setReloadKey((key) => key + 1)}>Try again</Button>}
          />
        </div>
      )}

      {!isLoadingLookups && !lookupError && (
        <Tabs value={tab} onChange={setTab} className="mt-6 lg:grid lg:grid-cols-[15rem_minmax(0,1fr)] lg:items-start lg:gap-8">
          {/* Below lg: one select (no sideways tab strip). From lg: a vertical list. */}
          <div className="mb-6 lg:hidden">
            <Select
              label="Section"
              value={tab}
              onChange={(event) => setTab(event.target.value)}
              options={SECTIONS.map((section) => ({ value: section.value, label: section.label }))}
            />
          </div>
          <nav aria-label="Policy sections" className="hidden lg:sticky lg:top-6 lg:block">
            <Tabs.List aria-label="Policy configuration sections" orientation="vertical">
              {SECTIONS.map((section) => (
                <Tabs.Tab key={section.value} value={section.value}>
                  <span aria-hidden="true" className="shrink-0">
                    {section.icon}
                  </span>
                  {section.label}
                </Tabs.Tab>
              ))}
            </Tabs.List>
          </nav>

          <div className="min-w-0">
            <Tabs.Panel value="interest-rates">
              <InterestRatesSection brands={brands} />
            </Tabs.Panel>
            <Tabs.Panel value="residual-value-matrix">
              <ResidualValueMatrixSection brands={brands} />
            </Tabs.Panel>
            <Tabs.Panel value="residual-estimates">
              <ResidualEstimatesSection />
            </Tabs.Panel>
            <Tabs.Panel value="mcda-weights">
              <MCDAWeightsSection />
            </Tabs.Panel>
            <Tabs.Panel value="operating-costs">
              <OperatingCostsSection />
            </Tabs.Panel>
            <Tabs.Panel value="subscription-plans">
              <SubscriptionPlansSection vehicles={vehicles} />
            </Tabs.Panel>
            <Tabs.Panel value="subscription-estimates">
              <SubscriptionEstimatesSection />
            </Tabs.Panel>
            <Tabs.Panel value="contract-penalty-rules">
              <ContractPenaltyRulesSection brands={brands} />
            </Tabs.Panel>
          </div>
        </Tabs>
      )}
    </div>
  );
}
