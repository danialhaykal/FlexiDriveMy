import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import axios from "axios";
import { Download } from "lucide-react";
import {
  archiveBrand,
  archiveVehicle,
  bulkImportVehicles,
  createBrand,
  createSpecDraft,
  createVehicle,
  fetchAdminBrands,
  fetchAdminVehicles,
  fetchBrandArchiveImpact,
  fetchVehicleArchiveImpact,
  unarchiveBrand,
  unarchiveVehicle,
  fetchResearchModels,
  fetchResearchVariants,
  fetchSpecDraft,
  patchSpecDraft,
  updateVehicle,
} from "../api/adminFleet";
import { listTotal } from "../api/allPages";
import { parseApiErrorMessage, parseApiFieldErrors } from "../lib/apiErrors";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { BODY_SEGMENT_OPTIONS, POWERTRAIN_OPTIONS } from "../types/catalog";

const BODY_SEGMENT_LABELS = Object.fromEntries(
  BODY_SEGMENT_OPTIONS.map((option) => [option.value, option.label]),
);
import type {
  AdminBrand,
  AdminVehicle,
  ArchiveImpact,
  ArchiveImpactGroup,
  BulkImportResponse,
  VehicleApiPayload,
  VehicleWritePayload,
} from "../types/adminFleet";
import { ROAD_TAX_CLASS_HELP_TEXT, ROAD_TAX_CLASS_OPTIONS } from "../types/adminFleet";
import type {
  ResearchModel,
  ResearchVariant,
  VehicleSpecDraft,
} from "../types/vehicleSpecDraft";
import { AdminListToolbar, NoMatchingRows, useAdminListFilter } from "../components/admin/AdminListToolbar";
import { RowActionsMenu } from "../components/admin/RowActionsMenu";
import type { RowAction } from "../components/admin/RowActionsMenu";
import { VehiclePhotoPlaceholder } from "../components/catalog/VehiclePhotoPlaceholder";
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
import { InfoTip } from "../components/ui/InfoTip";
import { Table } from "../components/ui/Table";
import { cn } from "../components/ui/cn";

// Batch 6A, UC010 - Fleet & Car Specification Management. The backend
// CRUD/bulk-import/audit-log plumbing already existed (apps.vehicles);
// this is purely the missing admin screen for it. Per UC010's own
// alternate-flow wording, a validation error on the add/edit form must
// show a message PER invalid field while leaving every other entered
// value exactly as typed - satisfied here simply by never clearing
// `formValues` on a failed submit, only `formErrors`.

const GENERIC_ERROR = "Could not load fleet data. Please try again.";

// Redesign UI-6a: an archived row (shown under Archived or All) is muted; its
// "Archived" badge says why.
const ARCHIVED_ROW_CLASS = "bg-page-bg [&>td]:text-ink-muted";

// FX-3 (X13): what tier_code means - the brand's price tier, the brand_code
// feature of the resale forecast (apps.vehicles.models.BrandTier, 1-5 from the
// training data's median resale prices). Blank = not set, and that brand's cars
// get the estimated depreciation curve.
export const TIER_LEGEND =
  "The brand's price tier for the resale forecast: Tier 1 has the highest resale values, Tier 5 the lowest. A brand with no tier gets the estimated depreciation curve.";

export function tierLabel(tierCode: string): string {
  return tierCode ? `Tier ${tierCode}` : "Not set";
}

// FX-3: the bulk-import columns, in one list for the help text and the CSV
// template (the server's apps.vehicles.imports REQUIRED_COLUMNS / OPTIONAL_COLUMNS).
export const BULK_IMPORT_REQUIRED_COLUMNS = [
  "brand",
  "name",
  "trim",
  "body_segment",
  "msrp",
  "engine_capacity_kw",
  "powertrain",
];
export const BULK_IMPORT_OPTIONAL_COLUMNS = ["engine_capacity_cc", "road_tax_class", "model_year", "thumbnail_url"];
export const BULK_IMPORT_TEMPLATE_FILENAME = "fleet_import_template.csv";

// A header-only CSV built in the browser (no endpoint).
export function bulkImportTemplateCsv(): string {
  return [...BULK_IMPORT_REQUIRED_COLUMNS, ...BULK_IMPORT_OPTIONAL_COLUMNS].join(",") + "\r\n";
}

function downloadBulkImportTemplate() {
  const url = URL.createObjectURL(new Blob([bulkImportTemplateCsv()], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = BULK_IMPORT_TEMPLATE_FILENAME;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

const EMPTY_VEHICLE_FORM: VehicleWritePayload = {
  brand: "",
  name: "",
  trim: "",
  body_segment: "",
  model_year: "",
  msrp: "",
  engine_capacity_kw: "",
  powertrain: "",
  engine_capacity_cc: "",
  road_tax_class: "",
  thumbnail_url: "",
};

// Run 1 fix batch 3: a class the server reports as the body type's usual one
// is shown as "Usual for the body type" (so changing the body type moves it
// too); an override is shown as itself. The server owns the body-type rule.
function roadTaxClassFormValue(vehicle: AdminVehicle): VehicleWritePayload["road_tax_class"] {
  return vehicle.road_tax_class_is_default === false ? vehicle.road_tax_class ?? "" : "";
}

// Mirrors the Vehicle Readiness amber note: a crossover, or a class set
// differently from the body type's usual one (never for a BEV - kW-taxed).
function needsRoadTaxClassCheck(vehicle: AdminVehicle): boolean {
  if (vehicle.powertrain === "bev") return false;
  return vehicle.body_segment === "crossover" || vehicle.road_tax_class_is_default === false;
}

// engine_capacity_kw is POWER OUTPUT in kW (legacy field name); engine
// displacement is engine_capacity_cc, and a battery electric vehicle has
// none (the new-vehicle contract - the server enforces it, this form just
// disables the input and clears the value for a BEV).
function vehicleToFormValues(vehicle: AdminVehicle): VehicleWritePayload {
  return {
    brand: vehicle.brand,
    name: vehicle.name,
    trim: vehicle.trim,
    body_segment: vehicle.body_segment,
    model_year: vehicle.model_year ?? "",
    msrp: vehicle.msrp,
    engine_capacity_kw: vehicle.engine_capacity_kw,
    powertrain: vehicle.powertrain,
    engine_capacity_cc: vehicle.engine_capacity_cc ?? "",
    road_tax_class: roadTaxClassFormValue(vehicle),
    thumbnail_url: vehicle.thumbnail_url,
  };
}

// F010 optional stretch goal - pre-fills the SAME Add Vehicle form state
// a fully-manual entry uses, from a READY draft's proposed_data. Every
// field stays exactly as editable as manual entry (nothing read-only) -
// this only supplies an initial value. thumbnail_url is deliberately
// never pre-filled (see VehicleSpecDraft's own backend docstring for
// why) - left blank for the admin to paste manually, same as today.
function draftToFormValues(draft: VehicleSpecDraft): VehicleWritePayload {
  const proposed = draft.proposed_data;
  return {
    brand: draft.brand,
    name: draft.model_name_query,
    trim: draft.trim_query,
    body_segment: (proposed.body_segment as VehicleWritePayload["body_segment"]) ?? "",
    model_year: proposed.model_year ? Number(proposed.model_year) : "",
    msrp: proposed.msrp ?? "",
    engine_capacity_kw: proposed.engine_capacity_kw ?? "",
    // Absent when the page doesn't say clearly (never guessed) - the admin
    // picks it, with the same "Not found" badge as every other field.
    powertrain: (proposed.powertrain as VehicleWritePayload["powertrain"]) ?? "",
    engine_capacity_cc: proposed.engine_capacity_cc ? Number(proposed.engine_capacity_cc) : "",
    // A spec page doesn't show the registration class: start from the body
    // type's usual one; the admin can change it to what the VOC says.
    road_tax_class: "",
    thumbnail_url: "",
  };
}

// paultan names cards with the full prefix ("BMW 3 Series 320i Sport"); the
// picker labels and the form's Name/Trim want just the tail ("320i Sport").
function stripPrefix(value: string, prefix: string): string {
  if (prefix && value.toLowerCase().startsWith(`${prefix.toLowerCase()} `)) {
    return value.slice(prefix.length + 1).trim();
  }
  return value;
}

// Variant cards usually repeat the model name, but not always - Mercedes
// lists "Mercedes-Benz C200 Avantgarde CKD" under "Mercedes-Benz C-Class" -
// so fall back to dropping just the brand.
function variantShortName(variantName: string, modelName: string, brandName: string): string {
  const withoutModel = stripPrefix(variantName, modelName);
  return withoutModel !== variantName ? withoutModel : stripPrefix(variantName, brandName);
}

// e.g. "320i Sport · 2026 · RM267,800 · 184 hp (no longer on sale)". The
// price is only reformatted with thousands separators for display - the
// value itself is exactly what the API returned.
function variantOptionLabel(variant: ResearchVariant, modelName: string, brandName: string): string {
  const parts = [variantShortName(variant.name, modelName, brandName), String(variant.year)];
  if (variant.msrp !== null) {
    const amount = Number(variant.msrp);
    parts.push(Number.isNaN(amount) ? `RM${variant.msrp}` : `RM${amount.toLocaleString("en-MY")}`);
  }
  if (variant.power_hp !== null) parts.push(`${variant.power_hp} hp`);
  const label = parts.join(" · ");
  return variant.on_sale ? label : `${label} (no longer on sale)`;
}

// Archiving a brand/vehicle cascades server-side (apps.vehicles.archiving);
// these only turn the API's integer counts into a readable sentence.
const IMPACT_NOUNS: Record<ArchiveImpactGroup, [string, string]> = {
  vehicles: ["vehicle", "vehicles"],
  interest_rates: ["interest rate", "interest rates"],
  residual_value_rows: ["residual value row", "residual value rows"],
  penalty_rules: ["penalty rule", "penalty rules"],
  subscription_plans: ["subscription plan", "subscription plans"],
};

function describeImpactCounts(impact: ArchiveImpact): string | null {
  const parts = (Object.keys(IMPACT_NOUNS) as ArchiveImpactGroup[])
    .filter((group) => (impact.counts[group] ?? 0) > 0)
    .map((group) => {
      const count = impact.counts[group] ?? 0;
      return `${count} ${IMPACT_NOUNS[group][count === 1 ? 0 : 1]}`;
    });
  if (parts.length === 0) return null;
  return parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

function describeSkipped(impact: ArchiveImpact): string[] {
  return impact.skipped.map((row) => `${row.label} stays archived - ${row.reason}.`);
}

interface ArchiveTarget {
  kind: "brand" | "vehicle";
  id: number;
  name: string;
  mode: "archive" | "restore";
}

const SPEC_DRAFT_POLL_INTERVAL_MS = 2000;
const SPEC_DRAFT_POLL_TIMEOUT_MS = 30000;

export function AdminFleetPage() {
  useDocumentTitle("Fleet Management");

  const [vehicles, setVehicles] = useState<AdminVehicle[]>([]);
  const [brands, setBrands] = useState<AdminBrand[]>([]);
  // Run 3 fix batch 4 (F-17): the server's row counts, for ListCapNotice.
  const [vehiclesTotal, setVehiclesTotal] = useState(0);
  const [brandsTotal, setBrandsTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingVehicleId, setEditingVehicleId] = useState<number | null>(null);
  // Run 1 fix batch 5 (G7): the updated_at the edit form was loaded with -
  // sent back so the server can refuse a save over someone else's change.
  const [editingUpdatedAt, setEditingUpdatedAt] = useState<string | null>(null);
  // UC010: "Vehicle added successfully." / "Vehicle updated successfully."
  const [saveNotice, setSaveNotice] = useState<string | null>(null);
  const [formValues, setFormValues] = useState<VehicleWritePayload>(EMPTY_VEHICLE_FORM);
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  // One confirm dialog for archiving AND reactivating brands and vehicles.
  const [archiveTarget, setArchiveTarget] = useState<ArchiveTarget | null>(null);
  const [archiveImpact, setArchiveImpact] = useState<ArchiveImpact | null>(null);
  const [isImpactLoading, setIsImpactLoading] = useState(false);
  const [impactError, setImpactError] = useState(false);
  const [isArchiving, setIsArchiving] = useState(false);
  const [archiveNotice, setArchiveNotice] = useState<{ text: string; details: string[] } | null>(null);

  const [bulkFile, setBulkFile] = useState<File | null>(null);
  const [bulkReport, setBulkReport] = useState<BulkImportResponse | null>(null);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [isBulkSubmitting, setIsBulkSubmitting] = useState(false);

  const [newBrandName, setNewBrandName] = useState("");
  const [newBrandTierCode, setNewBrandTierCode] = useState("");
  const [brandFormErrors, setBrandFormErrors] = useState<Record<string, string>>({});
  const [isBrandSubmitting, setIsBrandSubmitting] = useState(false);

  // F010 optional stretch goal - "Fetch Spec Draft" assist: a Brand ->
  // Model -> Variant picker over paultan.org's Car Buyer's Guide.
  const [isSpecSearchOpen, setIsSpecSearchOpen] = useState(false);
  const [specSearchBrand, setSpecSearchBrand] = useState<number | "">("");
  const [researchModels, setResearchModels] = useState<ResearchModel[]>([]);
  const [isLoadingModels, setIsLoadingModels] = useState(false);
  const [modelsMessage, setModelsMessage] = useState<string | null>(null);
  const [selectedModelUrl, setSelectedModelUrl] = useState("");
  const [researchVariants, setResearchVariants] = useState<ResearchVariant[]>([]);
  const [isLoadingVariants, setIsLoadingVariants] = useState(false);
  const [variantsMessage, setVariantsMessage] = useState<string | null>(null);
  const [selectedVariantUrl, setSelectedVariantUrl] = useState("");
  const [isSpecSearchSubmitting, setIsSpecSearchSubmitting] = useState(false);
  const [specSearchError, setSpecSearchError] = useState<string | null>(null);
  const [pollingDraftId, setPollingDraftId] = useState<number | null>(null);
  const [pollingStartedAt, setPollingStartedAt] = useState<number | null>(null);
  const [pollTimedOut, setPollTimedOut] = useState(false);
  // The draft a currently-open Add Vehicle form was pre-filled from, if
  // any - null for a normal manual "Add Vehicle"/"Edit" open. Drives the
  // missing-field badges/source link, and which draft (if any) gets the
  // fire-and-forget APPROVED patch after a successful save.
  const [activeDraft, setActiveDraft] = useState<VehicleSpecDraft | null>(null);

  function loadData() {
    setIsLoading(true);
    setLoadError(null);
    Promise.all([fetchAdminVehicles(), fetchAdminBrands()])
      .then(([vehicleData, brandData]) => {
        setVehicles(vehicleData);
        setBrands(brandData);
        setVehiclesTotal(listTotal(vehicleData));
        setBrandsTotal(listTotal(brandData));
      })
      .catch(() => setLoadError(GENERIC_ERROR))
      .finally(() => setIsLoading(false));
  }

  useEffect(() => {
    loadData();
  }, []);

  // Polls GET /vehicles/spec-drafts/<id>/ every ~2s while a fetch is in
  // flight (status=pending) - capped at ~30s, after which the admin sees
  // a "taking a while" note but can keep waiting (the draft keeps
  // existing server-side; nothing here cancels it) or fall back to a
  // blank manual form themselves.
  useEffect(() => {
    if (pollingDraftId === null) return;
    const intervalId = setInterval(() => {
      fetchSpecDraft(pollingDraftId)
        .then((draft) => {
          if (draft.status === "pending") {
            if (pollingStartedAt !== null && Date.now() - pollingStartedAt > SPEC_DRAFT_POLL_TIMEOUT_MS) {
              setPollTimedOut(true);
            }
            return;
          }
          setPollingDraftId(null);
          setPollTimedOut(false);
          setIsSpecSearchOpen(false);
          setActiveDraft(draft);
          setEditingVehicleId(null);
          // READY gets the full proposed_data pre-fill (plus name/trim from
          // the picked model/variant). NOT_FOUND and FAILED both fall back
          // to a completely blank form with only the brand filled in - the
          // form header then explains which one happened (FAILED shows the
          // server's error_message).
          setFormValues(
            draft.status === "ready" ? draftToFormValues(draft) : { ...EMPTY_VEHICLE_FORM, brand: draft.brand },
          );
          setFormErrors({});
          setIsFormOpen(true);
        })
        .catch(() => {
          setPollingDraftId(null);
          setSpecSearchError("Could not check the fetch status. Please try again.");
        });
    }, SPEC_DRAFT_POLL_INTERVAL_MS);
    return () => clearInterval(intervalId);
  }, [pollingDraftId, pollingStartedAt]);

  function openAddForm() {
    setActiveDraft(null);
    setEditingVehicleId(null);
    setEditingUpdatedAt(null);
    setSaveNotice(null);
    setFormValues(EMPTY_VEHICLE_FORM);
    setFormErrors({});
    setIsFormOpen(true);
  }

  function openEditForm(vehicle: AdminVehicle) {
    setActiveDraft(null);
    setEditingVehicleId(vehicle.id);
    setEditingUpdatedAt(vehicle.updated_at);
    setSaveNotice(null);
    setFormValues(vehicleToFormValues(vehicle));
    setFormErrors({});
    setIsFormOpen(true);
  }

  // Deep link from Vehicle Readiness ("Edit vehicle"): /admin/fleet?edit=<id>
  // opens that vehicle's edit form once the list has loaded, once per visit.
  // Reads the address bar directly (no router hook), so the page still renders
  // anywhere it already did.
  const deepLinkHandled = useRef(false);
  useEffect(() => {
    if (deepLinkHandled.current || vehicles.length === 0) return;
    const editId = Number(new URLSearchParams(window.location.search).get("edit"));
    if (!editId) return;
    deepLinkHandled.current = true;
    const target = vehicles.find((vehicle) => vehicle.id === editId);
    if (target) openEditForm(target);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vehicles]);

  function closeForm() {
    setIsFormOpen(false);
    setEditingVehicleId(null);
    setFormErrors({});
    setActiveDraft(null);
  }

  const specSearchBrandName = brands.find((brand) => brand.id === specSearchBrand)?.name ?? "";
  const selectedModel = researchModels.find((model) => model.url === selectedModelUrl);
  const selectedVariant = researchVariants.find((variant) => variant.url === selectedVariantUrl);

  function resetVariantStep() {
    setResearchVariants([]);
    setVariantsMessage(null);
    setSelectedVariantUrl("");
  }

  function resetModelStep() {
    setResearchModels([]);
    setModelsMessage(null);
    setSelectedModelUrl("");
    resetVariantStep();
  }

  async function handleFindModels() {
    if (!specSearchBrandName) return;
    resetModelStep();
    setSpecSearchError(null);
    setIsLoadingModels(true);
    try {
      const response = await fetchResearchModels(specSearchBrandName);
      setResearchModels(response.models);
      setModelsMessage(response.message ?? null);
    } catch (err: unknown) {
      setSpecSearchError(
        (axios.isAxiosError(err) && parseApiErrorMessage(err.response?.data)) ||
          "Could not load models. Please try again.",
      );
    } finally {
      setIsLoadingModels(false);
    }
  }

  async function handleSelectModel(modelUrl: string) {
    setSelectedModelUrl(modelUrl);
    resetVariantStep();
    setSpecSearchError(null);
    if (!modelUrl) return;
    setIsLoadingVariants(true);
    try {
      const response = await fetchResearchVariants(modelUrl);
      setResearchVariants(response.variants);
      setVariantsMessage(response.message ?? null);
    } catch (err: unknown) {
      setSpecSearchError(
        (axios.isAxiosError(err) && parseApiErrorMessage(err.response?.data)) ||
          "Could not load variants. Please try again.",
      );
    } finally {
      setIsLoadingVariants(false);
    }
  }

  async function handleSpecSearchSubmit(event: FormEvent) {
    event.preventDefault();
    if (specSearchBrand === "" || !selectedModel || !selectedVariant) return;
    setIsSpecSearchSubmitting(true);
    setSpecSearchError(null);
    const modelName = stripPrefix(selectedModel.name, specSearchBrandName);
    try {
      const draft = await createSpecDraft({
        brand: specSearchBrand,
        source_url: selectedVariant.url,
        model_name_query: modelName,
        trim_query: variantShortName(selectedVariant.name, selectedModel.name, specSearchBrandName),
      });
      setPollingDraftId(draft.id);
      setPollingStartedAt(Date.now());
      setPollTimedOut(false);
    } catch (err: unknown) {
      setSpecSearchError(
        (axios.isAxiosError(err) && parseApiErrorMessage(err.response?.data)) ||
          "Could not start the fetch. Please try again.",
      );
    } finally {
      setIsSpecSearchSubmitting(false);
    }
  }

  function closeSpecSearch() {
    setIsSpecSearchOpen(false);
    setSpecSearchBrand("");
    resetModelStep();
    setSpecSearchError(null);
    setPollingDraftId(null);
    setPollTimedOut(false);
  }

  async function handleFormSubmit(event: FormEvent) {
    event.preventDefault();
    setIsSubmitting(true);
    setFormErrors({});
    try {
      const payload: VehicleApiPayload = {
        ...formValues,
        brand: formValues.brand === "" ? "" : Number(formValues.brand),
        // Optional: a blank model year goes over as null, never an invented year.
        model_year: formValues.model_year === "" ? null : Number(formValues.model_year),
        // A blank cc (always the case for a BEV) goes over as null.
        engine_capacity_cc: formValues.engine_capacity_cc === "" ? null : Number(formValues.engine_capacity_cc),
      };
      const isEdit = editingVehicleId !== null;
      const saved = isEdit
        ? await updateVehicle(editingVehicleId, { ...payload, updated_at: editingUpdatedAt ?? undefined })
        : await createVehicle(payload);
      setVehicles((prev) => {
        if (editingVehicleId === null) return [...prev, saved];
        return prev.map((item) => (item.id === saved.id ? saved : item));
      });
      // Fire-and-forget traceability only (see VehicleSpecDraft's own
      // backend docstring) - this vehicle is already fully saved via the
      // exact same createVehicle() call manual entry uses; the draft
      // PATCH below is never required for that to succeed.
      if (activeDraft) {
        void patchSpecDraft(activeDraft.id, { status: "approved", approved_vehicle: saved.id });
      }
      closeForm();
      setSaveNotice(isEdit ? "Vehicle updated successfully." : "Vehicle added successfully.");
    } catch (err: unknown) {
      if (axios.isAxiosError(err) && err.response?.status === 400) {
        setFormErrors(parseApiFieldErrors(err.response.data));
      } else if (axios.isAxiosError(err) && err.response?.status === 409) {
        // Someone else saved this vehicle since it was loaded: keep every typed
        // value on screen and say so (the server's own message).
        setFormErrors({
          detail:
            parseApiErrorMessage(err.response.data) ??
            "This record was changed by someone else. Reload to see the latest version.",
        });
      } else {
        setFormErrors({ detail: "Could not save this vehicle. Please try again." });
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  // Load the archive/reactivate preview whenever the confirm dialog opens.
  useEffect(() => {
    if (archiveTarget === null) return;
    let cancelled = false;
    setArchiveImpact(null);
    setImpactError(false);
    setIsImpactLoading(true);
    const fetchImpact = archiveTarget.kind === "brand" ? fetchBrandArchiveImpact : fetchVehicleArchiveImpact;
    fetchImpact(archiveTarget.id)
      .then((impact) => {
        if (!cancelled) setArchiveImpact(impact);
      })
      .catch(() => {
        if (!cancelled) setImpactError(true);
      })
      .finally(() => {
        if (!cancelled) setIsImpactLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [archiveTarget]);

  function archiveDialogMessage(): string {
    if (archiveTarget === null) return "";
    const verb = archiveTarget.mode === "archive" ? "Archiving" : "Reactivating";
    if (isImpactLoading) return "Checking what else this affects…";
    if (impactError || archiveImpact === null) {
      return `Could not load what else ${verb.toLowerCase()} ${archiveTarget.name} affects. Its dependent records will still follow it.`;
    }
    const counts = describeImpactCounts(archiveImpact);
    if (archiveTarget.mode === "archive") {
      return counts
        ? `${verb} ${archiveTarget.name} will also archive ${counts}. Reactivating it later brings exactly these back.`
        : `${verb} ${archiveTarget.name} will not archive anything else.`;
    }
    return counts
      ? `${verb} ${archiveTarget.name} will also restore ${counts} archived along with it.`
      : `${verb} ${archiveTarget.name} will not restore anything else.`;
  }

  // A brand archive/restore changes vehicles too - re-read both lists
  // rather than guessing which rows the server cascaded to.
  async function refreshFleet() {
    const [vehicleData, brandData] = await Promise.all([fetchAdminVehicles(), fetchAdminBrands()]);
    setVehicles(vehicleData);
    setBrands(brandData);
    setVehiclesTotal(listTotal(vehicleData));
    setBrandsTotal(listTotal(brandData));
  }

  async function handleConfirmArchiveAction() {
    if (archiveTarget === null) return;
    const target = archiveTarget;
    setIsArchiving(true);
    try {
      if (target.mode === "archive") {
        await (target.kind === "brand" ? archiveBrand(target.id) : archiveVehicle(target.id));
        const counts = archiveImpact ? describeImpactCounts(archiveImpact) : null;
        setArchiveNotice({
          text: counts ? `${target.name} archived, along with ${counts}.` : `${target.name} archived.`,
          details: [],
        });
      } else {
        const { cascade } = await (target.kind === "brand" ? unarchiveBrand(target.id) : unarchiveVehicle(target.id));
        const counts = describeImpactCounts(cascade);
        setArchiveNotice({
          text: counts ? `${target.name} reactivated, along with ${counts}.` : `${target.name} reactivated.`,
          details: describeSkipped(cascade),
        });
      }
      setArchiveTarget(null);
      const nowActive = target.mode === "restore";
      if (target.kind === "brand") {
        // The change itself succeeded - a failed re-read only means the
        // vehicle list may lag until the next page load.
        await refreshFleet().catch(() =>
          setBrands((prev) => prev.map((item) => (item.id === target.id ? { ...item, is_active: nowActive } : item))),
        );
      } else {
        setVehicles((prev) => prev.map((item) => (item.id === target.id ? { ...item, is_active: nowActive } : item)));
      }
    } catch {
      setArchiveNotice({ text: `Could not update ${target.name}. Please try again.`, details: [] });
      setArchiveTarget(null);
    } finally {
      setIsArchiving(false);
    }
  }

  async function handleBulkImportSubmit(event: FormEvent) {
    event.preventDefault();
    if (!bulkFile) return;
    setIsBulkSubmitting(true);
    setBulkError(null);
    setBulkReport(null);
    try {
      const report = await bulkImportVehicles(bulkFile);
      setBulkReport(report);
      if (report.created.length > 0) {
        setVehicles((prev) => [...prev, ...report.created]);
      }
    } catch (err: unknown) {
      setBulkError(
        (axios.isAxiosError(err) && parseApiErrorMessage(err.response?.data)) ||
          "Could not process this file. Please try again.",
      );
    } finally {
      setIsBulkSubmitting(false);
    }
  }

  async function handleAddBrand(event: FormEvent) {
    event.preventDefault();
    setIsBrandSubmitting(true);
    setBrandFormErrors({});
    try {
      const brand = await createBrand({ name: newBrandName, tier_code: newBrandTierCode });
      setBrands((prev) => [...prev, brand]);
      setNewBrandName("");
      setNewBrandTierCode("");
    } catch (err: unknown) {
      if (axios.isAxiosError(err) && err.response?.status === 400) {
        setBrandFormErrors(parseApiFieldErrors(err.response.data));
      } else {
        setBrandFormErrors({ detail: "Could not save this brand. Please try again." });
      }
    } finally {
      setIsBrandSubmitting(false);
    }
  }

  // Live-walkthrough finding 5: the vehicle Add/Edit form's own Brand
  // select must not offer every brand including archived ones. This is
  // the vehicle form's filtered list: active brands, plus - when editing
  // - the vehicle's current brand even if it's since been archived, so
  // editing an existing vehicle never forces also changing its brand
  // away from an archived one it's still correctly pointed at. (The
  // Brands management table further down reads `brands` directly, not
  // this list, and correctly keeps showing archived brands there.)
  function isMissingFromDraft(fieldName: string): boolean {
    return activeDraft?.missing_fields.includes(fieldName) ?? false;
  }

  const vehicleFormBrandOptions = [
    { value: "", label: "Select a brand..." },
    ...brands
      .filter((brand) => brand.is_active || String(brand.id) === String(formValues.brand))
      .map((brand) => ({
        value: String(brand.id),
        label: brand.is_active ? brand.name : `${brand.name} (archived)`,
      })),
  ];

  // Redesign UI-6a: the shared admin list pattern - Active by default, all rows
  // still loaded (F-17), so All plus a search reaches every one.
  const [vehicleBrandFilter, setVehicleBrandFilter] = useState<number | "">("");
  const vehicleList = useAdminListFilter(
    vehicles,
    (vehicle) => vehicle.is_active,
    (vehicle) => `${vehicle.brand_name} ${vehicle.name} ${vehicle.trim}`,
    (vehicle) => vehicleBrandFilter === "" || vehicle.brand === vehicleBrandFilter,
  );
  const brandList = useAdminListFilter(brands, (item) => item.is_active, (item) => `${item.name} ${item.tier_code}`);
  // FX-3 (X6): under Active the brand filter offers only active brands, so a
  // brand chosen under Archived / All that is archived is cleared there.
  const vehicleStatus = vehicleList.status;
  useEffect(() => {
    if (vehicleStatus !== "active" || vehicleBrandFilter === "") return;
    if (!brands.some((item) => item.id === vehicleBrandFilter && item.is_active)) setVehicleBrandFilter("");
  }, [vehicleStatus, vehicleBrandFilter, brands]);
  // From md a table; below it one compact card per vehicle (one DOM at a time).
  const isWide = useMediaQuery("(min-width: 768px)", true);

  function vehicleLabel(vehicle: AdminVehicle): string {
    return `${vehicle.brand_name} ${vehicle.name} ${vehicle.trim}`;
  }

  function vehicleActions(vehicle: AdminVehicle): RowAction[] {
    const target = { kind: "vehicle" as const, id: vehicle.id, name: vehicleLabel(vehicle) };
    return [
      { label: "Edit", onSelect: () => openEditForm(vehicle) },
      vehicle.is_active
        ? { label: "Archive", tone: "danger", onSelect: () => setArchiveTarget({ ...target, mode: "archive" }) }
        : { label: "Reactivate", onSelect: () => setArchiveTarget({ ...target, mode: "restore" }) },
    ];
  }

  function brandActions(item: AdminBrand): RowAction[] {
    const target = { kind: "brand" as const, id: item.id, name: item.name };
    return [
      item.is_active
        ? { label: "Archive", tone: "danger", onSelect: () => setArchiveTarget({ ...target, mode: "archive" }) }
        : { label: "Reactivate", onSelect: () => setArchiveTarget({ ...target, mode: "restore" }) },
    ];
  }

  function vehicleStatusBadges(vehicle: AdminVehicle) {
    return (
      <div className="flex flex-wrap gap-1">
        {vehicle.is_active ? <Badge tone="positive">Active</Badge> : <Badge tone="neutral">Archived</Badge>}
        {/* Rows entered before powertrain/cc existed - edit
            and complete them (never guessed server-side). */}
        {!vehicle.spec_complete && <Badge tone="warning">Needs specs</Badge>}
        {needsRoadTaxClassCheck(vehicle) && <Badge tone="warning">Check road-tax class on the VOC</Badge>}
      </div>
    );
  }

  function vehiclePhoto(vehicle: AdminVehicle, className: string) {
    return (
      <div className={cn("shrink-0 overflow-hidden rounded-control border border-border bg-surface-subtle", className)}>
        {vehicle.thumbnail_url ? (
          <img src={vehicle.thumbnail_url} alt="" loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <VehiclePhotoPlaceholder brandName={vehicle.brand_name} modelName={vehicle.name} size="xs" />
        )}
      </div>
    );
  }

  function formatMsrp(msrp: string): string {
    return Number(msrp).toLocaleString("en-MY", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  const brandFilterOptions = [
    { value: "", label: "All brands" },
    ...brands
      .filter((item) => vehicleStatus !== "active" || item.is_active)
      .map((item) => ({ value: String(item.id), label: item.is_active ? item.name : `${item.name} (archived)` })),
  ];

  return (
    <div className="mx-auto max-w-6xl px-4 pb-16 pt-8 sm:pt-10">
      <PageHeader
        title="Fleet management"
        subtitle="Cars and brands in the catalog."
        actions={
          !isFormOpen && (
            <>
              <Button
                variant="secondary"
                onClick={() => {
                  closeForm();
                  setIsSpecSearchOpen(true);
                }}
              >
                Fetch Spec Draft (beta)
              </Button>
              <Button onClick={openAddForm}>Add Vehicle</Button>
            </>
          )
        }
      />

      {isLoading && <LoadingSkeleton className="mt-6 h-64 w-full" />}
      {!isLoading && loadError && (
        <div role="alert" className="mt-6">
          <EmptyState
            title="Fleet data unavailable"
            description={loadError}
            action={<Button onClick={loadData}>Try again</Button>}
          />
        </div>
      )}

      {!isLoading && !loadError && (
        <div className="mt-6 flex flex-col gap-6">
          {archiveNotice && (
            <div role="status" className="rounded-card border border-border bg-surface p-4 text-small text-ink">
              <div className="flex items-start justify-between gap-4">
                <p>{archiveNotice.text}</p>
                <Button variant="ghost" onClick={() => setArchiveNotice(null)}>
                  Dismiss
                </Button>
              </div>
              {archiveNotice.details.length > 0 && (
                <ul className="mt-2 list-disc pl-5 text-ink-muted">
                  {archiveNotice.details.map((detail) => (
                    <li key={detail}>{detail}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {saveNotice && (
            <div
              role="status"
              className="flex items-start justify-between gap-4 rounded-card border border-positive-200 bg-positive-50 p-4 text-small text-positive-700"
            >
              <p>{saveNotice}</p>
              <Button variant="ghost" onClick={() => setSaveNotice(null)}>
                Dismiss
              </Button>
            </div>
          )}

          {isSpecSearchOpen && (
            <Card>
              <h2 className="text-h3 font-semibold text-ink">Fetch Spec Draft (beta)</h2>
              <p className="mt-1 text-small text-ink-muted">
                Pick a variant from paultan.org's Car Buyer's Guide and pre-fill the Add Vehicle
                form below - every field stays editable, and nothing is saved to the catalog until
                you review and click Create Vehicle yourself.
              </p>
              <form className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3" onSubmit={handleSpecSearchSubmit}>
                <div className="flex flex-col gap-2">
                  <Select
                    label="Brand"
                    value={specSearchBrand === "" ? "" : String(specSearchBrand)}
                    onChange={(e) => {
                      setSpecSearchBrand(e.target.value === "" ? "" : Number(e.target.value));
                      resetModelStep();
                    }}
                    options={[
                      { value: "", label: "Select a brand..." },
                      ...brands
                        .filter((item) => item.is_active)
                        .map((item) => ({ value: String(item.id), label: item.name })),
                    ]}
                  />
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={handleFindModels}
                    isLoading={isLoadingModels}
                    disabled={specSearchBrand === "" || isLoadingModels || pollingDraftId !== null}
                  >
                    Find models
                  </Button>
                </div>

                <div className="flex flex-col gap-2">
                  <Select
                    label="Model"
                    value={selectedModelUrl}
                    onChange={(e) => handleSelectModel(e.target.value)}
                    disabled={researchModels.length === 0 || pollingDraftId !== null}
                    options={[
                      {
                        value: "",
                        label: isLoadingModels ? "Loading models…" : "Select a model...",
                      },
                      ...[...researchModels]
                        .sort((a, b) => Number(b.on_sale) - Number(a.on_sale))
                        .map((model) => ({
                          value: model.url,
                          label: [model.name, model.price_text].filter(Boolean).join(" · ") +
                            (model.on_sale ? "" : " (no longer on sale)"),
                        })),
                    ]}
                  />
                  {modelsMessage && <p className="text-small text-ink-muted">{modelsMessage}</p>}
                </div>

                <div className="flex flex-col gap-2">
                  <Select
                    label="Variant"
                    value={selectedVariantUrl}
                    onChange={(e) => setSelectedVariantUrl(e.target.value)}
                    disabled={researchVariants.length === 0 || pollingDraftId !== null}
                    options={[
                      {
                        value: "",
                        label: isLoadingVariants ? "Loading variants…" : "Select a variant...",
                      },
                      ...researchVariants.map((variant) => ({
                        value: variant.url,
                        label: variantOptionLabel(variant, selectedModel?.name ?? "", specSearchBrandName),
                      })),
                    ]}
                  />
                  {variantsMessage && <p className="text-small text-ink-muted">{variantsMessage}</p>}
                </div>

                {specSearchError && (
                  <p className="md:col-span-3 text-small text-danger-700">{specSearchError}</p>
                )}

                {pollingDraftId !== null && (
                  <p className="md:col-span-3 text-small text-ink-muted">
                    {pollTimedOut
                      ? "Still looking - taking a while. You can keep waiting, or fill in the form manually."
                      : "Fetching this variant's spec sheet…"}
                  </p>
                )}

                <div className="flex gap-2 md:col-span-3">
                  <Button
                    type="submit"
                    isLoading={isSpecSearchSubmitting}
                    disabled={!selectedVariant || pollingDraftId !== null}
                  >
                    Fetch Spec Draft
                  </Button>
                  <Button type="button" variant="ghost" onClick={closeSpecSearch}>
                    Cancel
                  </Button>
                </div>
              </form>
            </Card>
          )}

          {isFormOpen && (
            <Card>
              <h2 className="text-h3 font-semibold text-ink">
                {editingVehicleId === null ? "Add Vehicle" : "Edit Vehicle"}
              </h2>
              {activeDraft && activeDraft.status === "ready" && (
                <p className="mt-1 text-small text-ink-muted">
                  Pre-filled from{" "}
                  <a
                    href={activeDraft.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-primary-700 underline"
                  >
                    {activeDraft.source_url}
                  </a>{" "}
                  - please review every field before saving.
                </p>
              )}
              {activeDraft && activeDraft.status === "not_found" && (
                <p className="mt-1 text-small text-ink-muted">
                  No matching spec page was found - fill in the form manually below.
                </p>
              )}
              {activeDraft && activeDraft.status === "failed" && (
                <p className="mt-1 text-small text-danger-700">
                  The spec fetch failed ({activeDraft.error_message || "unknown error"}) - fill in the
                  form manually below.
                </p>
              )}
              <form className="mt-5 grid grid-cols-1 gap-x-6 gap-y-4 md:grid-cols-2" onSubmit={handleFormSubmit}>
                <Select
                  label="Brand"
                  value={formValues.brand === "" ? "" : String(formValues.brand)}
                  onChange={(e) =>
                    setFormValues((prev) => ({
                      ...prev,
                      brand: e.target.value === "" ? "" : Number(e.target.value),
                    }))
                  }
                  options={vehicleFormBrandOptions}
                  error={formErrors.brand}
                />
                <Input
                  label="Name"
                  value={formValues.name}
                  onChange={(e) => setFormValues((prev) => ({ ...prev, name: e.target.value }))}
                  error={formErrors.name}
                />
                <Input
                  label="Trim"
                  value={formValues.trim}
                  onChange={(e) => setFormValues((prev) => ({ ...prev, trim: e.target.value }))}
                  error={formErrors.trim}
                />
                <div className="flex flex-col gap-1.5">
                  <Select
                    label="Body segment"
                    value={formValues.body_segment}
                    onChange={(e) =>
                      setFormValues((prev) => ({
                        ...prev,
                        body_segment: e.target.value as VehicleWritePayload["body_segment"],
                      }))
                    }
                    options={[{ value: "", label: "Select..." }, ...BODY_SEGMENT_OPTIONS]}
                    error={formErrors.body_segment}
                  />
                  {isMissingFromDraft("body_segment") && (
                    <Badge tone="warning">Not found - please fill in</Badge>
                  )}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Input
                    label="Model year"
                    type="number"
                    value={formValues.model_year === "" ? "" : String(formValues.model_year)}
                    onChange={(e) =>
                      setFormValues((prev) => ({
                        ...prev,
                        model_year: e.target.value === "" ? "" : Number(e.target.value),
                      }))
                    }
                    error={formErrors.model_year}
                  />
                  {isMissingFromDraft("model_year") && (
                    <Badge tone="warning">Not found - please fill in</Badge>
                  )}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Input
                    label="MSRP (RM)"
                    value={formValues.msrp}
                    onChange={(e) => setFormValues((prev) => ({ ...prev, msrp: e.target.value }))}
                    error={formErrors.msrp}
                  />
                  {isMissingFromDraft("msrp") && <Badge tone="warning">Not found - please fill in</Badge>}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Input
                    label="Power output (kW)"
                    value={formValues.engine_capacity_kw}
                    onChange={(e) =>
                      setFormValues((prev) => ({ ...prev, engine_capacity_kw: e.target.value }))
                    }
                    error={formErrors.engine_capacity_kw}
                  />
                  {isMissingFromDraft("engine_capacity_kw") && (
                    <Badge tone="warning">Not found - please fill in</Badge>
                  )}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Select
                    label="Powertrain"
                    value={formValues.powertrain}
                    onChange={(e) => {
                      const powertrain = e.target.value as VehicleWritePayload["powertrain"];
                      setFormValues((prev) => ({
                        ...prev,
                        powertrain,
                        // A BEV has no engine capacity: clear any cc already typed.
                        engine_capacity_cc: powertrain === "bev" ? "" : prev.engine_capacity_cc,
                      }));
                    }}
                    options={[{ value: "", label: "Select..." }, ...POWERTRAIN_OPTIONS]}
                    error={formErrors.powertrain}
                  />
                  {isMissingFromDraft("powertrain") && (
                    <Badge tone="warning">Not found - please fill in</Badge>
                  )}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Input
                    label="Engine capacity (cc)"
                    type="number"
                    value={formValues.engine_capacity_cc === "" ? "" : String(formValues.engine_capacity_cc)}
                    disabled={formValues.powertrain === "bev"}
                    onChange={(e) =>
                      setFormValues((prev) => ({
                        ...prev,
                        engine_capacity_cc: e.target.value === "" ? "" : Number(e.target.value),
                      }))
                    }
                    error={formErrors.engine_capacity_cc}
                  />
                  {formValues.powertrain === "bev" && (
                    <p className="text-small text-ink-muted">Not applicable to a battery electric vehicle.</p>
                  )}
                  {isMissingFromDraft("engine_capacity_cc") && (
                    <Badge tone="warning">Not found - please fill in</Badge>
                  )}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Select
                    label="Road-tax class"
                    value={formValues.road_tax_class}
                    disabled={formValues.powertrain === "bev"}
                    onChange={(e) =>
                      setFormValues((prev) => ({
                        ...prev,
                        road_tax_class: e.target.value as VehicleWritePayload["road_tax_class"],
                      }))
                    }
                    options={ROAD_TAX_CLASS_OPTIONS}
                    helpText={ROAD_TAX_CLASS_HELP_TEXT}
                    error={formErrors.road_tax_class}
                  />
                  {formValues.powertrain === "bev" && (
                    <p className="text-small text-ink-muted">
                      Electric cars are taxed by motor kW, not by class.
                    </p>
                  )}
                  {formValues.powertrain !== "bev" &&
                    (formValues.body_segment === "crossover" || formValues.road_tax_class !== "") && (
                      <Badge tone="warning">Check road-tax class on the VOC</Badge>
                    )}
                </div>
                <Input
                  label="Thumbnail URL"
                  value={formValues.thumbnail_url}
                  onChange={(e) =>
                    setFormValues((prev) => ({ ...prev, thumbnail_url: e.target.value }))
                  }
                  error={formErrors.thumbnail_url}
                />

                {formErrors.detail && (
                  <p className="md:col-span-2 text-small text-danger-700">{formErrors.detail}</p>
                )}

                <div className="flex gap-2 border-t border-border pt-4 md:col-span-2">
                  <Button type="submit" isLoading={isSubmitting}>
                    {editingVehicleId === null ? "Create Vehicle" : "Save Changes"}
                  </Button>
                  <Button type="button" variant="ghost" onClick={closeForm}>
                    Cancel
                  </Button>
                </div>
              </form>
            </Card>
          )}

          <section aria-labelledby="fleet-vehicles-heading">
            <Card padding="none">
              <div className="flex flex-col gap-4 p-4 sm:p-6">
                <h2 id="fleet-vehicles-heading" className="text-h3 font-semibold text-ink">
                  Vehicles
                </h2>
                <AdminListToolbar searchLabel="Search vehicles" {...vehicleList.toolbarProps}>
                  <div className="w-full sm:w-48">
                    <Select
                      label="Filter by brand"
                      value={vehicleBrandFilter === "" ? "" : String(vehicleBrandFilter)}
                      onChange={(e) => setVehicleBrandFilter(e.target.value === "" ? "" : Number(e.target.value))}
                      options={brandFilterOptions}
                    />
                  </div>
                </AdminListToolbar>
              </div>
              {isWide ? (
                <Table>
                  <Table.Head>
                    <Table.Row>
                      <Table.HeaderCell>
                        <span className="sr-only">Photo</span>
                      </Table.HeaderCell>
                      <Table.HeaderCell>Car</Table.HeaderCell>
                      <Table.HeaderCell>Segment</Table.HeaderCell>
                      <Table.HeaderCell numeric>MSRP (RM)</Table.HeaderCell>
                      <Table.HeaderCell>Status</Table.HeaderCell>
                      <Table.HeaderCell>
                        <span className="sr-only">Actions</span>
                      </Table.HeaderCell>
                    </Table.Row>
                  </Table.Head>
                  <Table.Body>
                    {vehicleList.visible.map((vehicle) => (
                      <Table.Row key={vehicle.id} className={vehicle.is_active ? undefined : ARCHIVED_ROW_CLASS}>
                        <Table.Cell className="w-20">{vehiclePhoto(vehicle, "h-10 w-16")}</Table.Cell>
                        <Table.Cell>
                          <div className="text-caption text-ink-muted">{vehicle.brand_name}</div>
                          <div className="font-medium">
                            {vehicle.name} <span className="font-normal">{vehicle.trim}</span>
                          </div>
                        </Table.Cell>
                        <Table.Cell>{BODY_SEGMENT_LABELS[vehicle.body_segment] ?? vehicle.body_segment}</Table.Cell>
                        <Table.Cell numeric>{formatMsrp(vehicle.msrp)}</Table.Cell>
                        <Table.Cell>{vehicleStatusBadges(vehicle)}</Table.Cell>
                        <Table.Cell className="w-12 text-right">
                          <RowActionsMenu label={`Actions for ${vehicleLabel(vehicle)}`} actions={vehicleActions(vehicle)} />
                        </Table.Cell>
                      </Table.Row>
                    ))}
                  </Table.Body>
                </Table>
              ) : (
                <ul className="divide-y divide-border border-t border-border" aria-label="Vehicles">
                  {vehicleList.visible.map((vehicle) => (
                    <li
                      key={vehicle.id}
                      className={cn("flex items-start gap-3 p-4", !vehicle.is_active && "bg-page-bg")}
                    >
                      {vehiclePhoto(vehicle, "h-12 w-20")}
                      <div className="min-w-0 flex-1">
                        <p className="text-caption text-ink-muted">{vehicle.brand_name}</p>
                        <p className={cn("font-medium", vehicle.is_active ? "text-ink" : "text-ink-muted")}>
                          {vehicle.name} <span className="font-normal">{vehicle.trim}</span>
                        </p>
                        <p className="mt-0.5 text-caption text-ink-muted">
                          {BODY_SEGMENT_LABELS[vehicle.body_segment] ?? vehicle.body_segment} · RM {formatMsrp(vehicle.msrp)}
                        </p>
                        <div className="mt-2">{vehicleStatusBadges(vehicle)}</div>
                      </div>
                      <RowActionsMenu label={`Actions for ${vehicleLabel(vehicle)}`} actions={vehicleActions(vehicle)} />
                    </li>
                  ))}
                </ul>
              )}
              {vehicles.length === 0 ? (
                <EmptyState
                  className="border-0"
                  title="No vehicles yet"
                  description="Add a vehicle or bulk-import a spreadsheet to get started."
                />
              ) : (
                vehicleList.visible.length === 0 && (
                  <NoMatchingRows status={vehicleList.status} hasSearch={vehicleList.search.trim() !== "" || vehicleBrandFilter !== ""} />
                )
              )}
            </Card>
            <ListCapNotice shown={vehicles.length} total={vehiclesTotal} />
          </section>

          <Card>
            <h2 className="text-h3 font-semibold text-ink">Bulk Import</h2>
            <p className="mt-1 text-small text-ink-muted">
              Upload a CSV or Excel file. Every row is validated against the
              same rules as the single-entry form above; only valid rows are created.
            </p>
            <InfoExpander summary="Columns and file rules" className="mt-2">
              <p>
                Required columns: brand, name, trim, body_segment, msrp, engine_capacity_kw (power
                output in kW) and powertrain (petrol, diesel, mild_hybrid, hybrid, phev or
                bev). Optional columns: engine_capacity_cc (engine displacement in cc - required for every
                powertrain except bev, and must be empty for bev), road_tax_class (saloon or non_saloon - leave
                blank for the body type&apos;s usual class), model_year and thumbnail_url. The CSV template
                below has exactly these columns.
              </p>
            </InfoExpander>
            <div className="mt-3">
              <Button type="button" variant="secondary" onClick={downloadBulkImportTemplate}>
                <Download className="h-4 w-4" aria-hidden="true" />
                Download CSV template
              </Button>
            </div>
            <form className="mt-4 flex flex-wrap items-end gap-3" onSubmit={handleBulkImportSubmit}>
              <input
                type="file"
                accept=".csv,.xlsx"
                aria-label="Bulk import file"
                onChange={(e) => setBulkFile(e.target.files?.[0] ?? null)}
                className="max-w-full text-small text-ink"
              />
              <Button type="submit" isLoading={isBulkSubmitting} disabled={!bulkFile}>
                Import
              </Button>
            </form>

            {bulkError && <p className="mt-3 text-small text-danger-700">{bulkError}</p>}

            {bulkReport && (
              <div className="mt-4 flex flex-col gap-3">
                <div className="flex flex-wrap gap-4 text-small text-ink">
                  <span>Total rows: {bulkReport.total_rows}</span>
                  <span className="text-positive-700">Created: {bulkReport.created_count}</span>
                  <span className="text-danger-700">Errors: {bulkReport.error_count}</span>
                </div>
                {bulkReport.errors.length > 0 && (
                  <Table>
                    <Table.Head>
                      <Table.Row>
                        <Table.HeaderCell>Row</Table.HeaderCell>
                        <Table.HeaderCell>Errors</Table.HeaderCell>
                      </Table.Row>
                    </Table.Head>
                    <Table.Body>
                      {bulkReport.errors.map((rowError) => (
                        <Table.Row key={rowError.row}>
                          <Table.Cell>{rowError.row}</Table.Cell>
                          <Table.Cell>
                            <ul className="list-disc pl-4">
                              {Object.entries(rowError.errors).map(([field, message]) => (
                                <li key={field}>
                                  <span className="font-medium">{field}:</span>{" "}
                                  {Array.isArray(message) ? message.join(" ") : message}
                                </li>
                              ))}
                            </ul>
                          </Table.Cell>
                        </Table.Row>
                      ))}
                    </Table.Body>
                  </Table>
                )}
              </div>
            )}
          </Card>

          <section aria-labelledby="fleet-brands-heading">
            <Card padding="none">
              <div className="flex flex-col gap-4 p-4 sm:p-6">
                <h2 id="fleet-brands-heading" className="text-h3 font-semibold text-ink">
                  Brands
                </h2>
                <form className="flex flex-wrap items-end gap-3" onSubmit={handleAddBrand}>
                  <Input
                    label="Name"
                    value={newBrandName}
                    onChange={(e) => setNewBrandName(e.target.value)}
                    error={brandFormErrors.name}
                  />
                  <Input
                    label="Tier code"
                    value={newBrandTierCode}
                    onChange={(e) => setNewBrandTierCode(e.target.value)}
                    error={brandFormErrors.tier_code}
                  />
                  <Button type="submit" variant="secondary" isLoading={isBrandSubmitting}>
                    Add Brand
                  </Button>
                </form>
                {brandFormErrors.detail && <p className="text-small text-danger-700">{brandFormErrors.detail}</p>}
                <AdminListToolbar searchLabel="Search brands" {...brandList.toolbarProps} />
              </div>

              <Table>
                <Table.Head>
                  <Table.Row>
                    <Table.HeaderCell>Name</Table.HeaderCell>
                    <Table.HeaderCell>
                      <span className="inline-flex items-center gap-1">
                        Price tier
                        <InfoTip label="About price tiers">{TIER_LEGEND}</InfoTip>
                      </span>
                    </Table.HeaderCell>
                    <Table.HeaderCell>Status</Table.HeaderCell>
                    <Table.HeaderCell>
                      <span className="sr-only">Actions</span>
                    </Table.HeaderCell>
                  </Table.Row>
                </Table.Head>
                <Table.Body>
                  {brandList.visible.map((item) => (
                    <Table.Row key={item.id} className={item.is_active ? undefined : ARCHIVED_ROW_CLASS}>
                      <Table.Cell>{item.name}</Table.Cell>
                      <Table.Cell className="whitespace-nowrap">{tierLabel(item.tier_code)}</Table.Cell>
                      <Table.Cell>
                        {item.is_active ? <Badge tone="positive">Active</Badge> : <Badge tone="neutral">Archived</Badge>}
                      </Table.Cell>
                      <Table.Cell className="w-12 text-right">
                        <RowActionsMenu label={`Actions for ${item.name}`} actions={brandActions(item)} />
                      </Table.Cell>
                    </Table.Row>
                  ))}
                </Table.Body>
              </Table>
              {brands.length > 0 && brandList.visible.length === 0 && (
                <NoMatchingRows status={brandList.status} hasSearch={brandList.search.trim() !== ""} />
              )}
            </Card>
            <ListCapNotice shown={brands.length} total={brandsTotal} />
          </section>
        </div>
      )}

      <ConfirmDialog
        isOpen={archiveTarget !== null}
        title={
          archiveTarget === null
            ? ""
            : `${archiveTarget.mode === "archive" ? "Archive" : "Reactivate"} this ${archiveTarget.kind}?`
        }
        message={archiveDialogMessage()}
        details={archiveTarget?.mode === "restore" && archiveImpact ? describeSkipped(archiveImpact) : []}
        confirmLabel={archiveTarget?.mode === "restore" ? "Reactivate" : "Archive"}
        isConfirming={isArchiving}
        isConfirmDisabled={isImpactLoading}
        onConfirm={() => void handleConfirmArchiveAction()}
        onCancel={() => setArchiveTarget(null)}
      />
    </div>
  );
}
