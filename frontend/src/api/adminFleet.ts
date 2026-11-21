import { apiClient } from "./client";
import { fetchAllPages } from "./allPages";
import type { FullList } from "./allPages";
import type {
  AdminBrand,
  AdminVehicle,
  ArchiveImpact,
  BrandWritePayload,
  BulkImportResponse,
  UnarchiveBrandResponse,
  UnarchiveVehicleResponse,
  VehicleApiPayload,
} from "../types/adminFleet";
import type {
  ResearchModelsResponse,
  ResearchVariantsResponse,
  VehicleSpecDraft,
  VehicleSpecDraftApprovalPayload,
  VehicleSpecDraftCreatePayload,
} from "../types/vehicleSpecDraft";

// Batch 6A, UC010 - admin-only fleet CRUD (apps.vehicles.views::
// BrandViewSet / VehicleModelViewSet), distinct from the public
// read-only ./catalog.ts (CatalogVehicleViewSet). include_archived=true
// is AuditedModelViewSet's own escape hatch (apps/audit/mixins.py) -
// UC010 explicitly wants archived rows visible in the admin list, not
// just active ones.
//
// Run 3 fix batch 4 (F-17): every page, not just the first 25 rows.

export async function fetchAdminVehicles(): Promise<FullList<AdminVehicle>> {
  return fetchAllPages<AdminVehicle>("/vehicles/models/", { include_archived: true });
}

export async function createVehicle(payload: VehicleApiPayload): Promise<AdminVehicle> {
  const { data } = await apiClient.post<AdminVehicle>("/vehicles/models/", payload);
  return data;
}

export async function updateVehicle(
  id: number,
  payload: VehicleApiPayload,
): Promise<AdminVehicle> {
  const { data } = await apiClient.put<AdminVehicle>(`/vehicles/models/${id}/`, payload);
  return data;
}

export async function archiveVehicle(id: number): Promise<void> {
  await apiClient.delete(`/vehicles/models/${id}/`);
}

export async function bulkImportVehicles(file: File): Promise<BulkImportResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post<BulkImportResponse>("/vehicles/models/bulk_import/", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function fetchAdminBrands(): Promise<FullList<AdminBrand>> {
  return fetchAllPages<AdminBrand>("/vehicles/brands/", { include_archived: true });
}

export async function createBrand(payload: BrandWritePayload): Promise<AdminBrand> {
  const { data } = await apiClient.post<AdminBrand>("/vehicles/brands/", payload);
  return data;
}

export async function archiveBrand(id: number): Promise<void> {
  await apiClient.delete(`/vehicles/brands/${id}/`);
}

// Archiving a brand/vehicle cascades server-side (apps.vehicles.archiving);
// archive-impact is the read-only preview of what it (or a reactivation)
// would also change, and unarchive returns what actually came back.

export async function fetchBrandArchiveImpact(id: number): Promise<ArchiveImpact> {
  const { data } = await apiClient.get<ArchiveImpact>(`/vehicles/brands/${id}/archive-impact/`);
  return data;
}

export async function fetchVehicleArchiveImpact(id: number): Promise<ArchiveImpact> {
  const { data } = await apiClient.get<ArchiveImpact>(`/vehicles/models/${id}/archive-impact/`);
  return data;
}

export async function unarchiveBrand(id: number): Promise<UnarchiveBrandResponse> {
  const { data } = await apiClient.post<UnarchiveBrandResponse>(`/vehicles/brands/${id}/unarchive/`);
  return data;
}

export async function unarchiveVehicle(id: number): Promise<UnarchiveVehicleResponse> {
  const { data } = await apiClient.post<UnarchiveVehicleResponse>(`/vehicles/models/${id}/unarchive/`);
  return data;
}

// F010 optional stretch goal - UC010's "Fetch Spec Draft" admin assist
// (apps.vehicles.views::VehicleSpecDraftViewSet). fetchResearchModels/
// fetchResearchVariants populate the Brand -> Model -> Variant picker from
// paultan.org's buyer's guide (cached server-side for 12h). createSpecDraft
// returns immediately (status=pending) - the actual fetch runs as a
// background Celery task; fetchSpecDraft is for polling it, and
// patchSpecDraft is the fire-and-forget traceability update after the
// admin's own real Add Vehicle save succeeds (never required for it).

export async function fetchResearchModels(brand: string): Promise<ResearchModelsResponse> {
  const { data } = await apiClient.get<ResearchModelsResponse>("/vehicles/spec-drafts/catalog-models/", {
    params: { brand },
  });
  return data;
}

export async function fetchResearchVariants(modelUrl: string): Promise<ResearchVariantsResponse> {
  const { data } = await apiClient.get<ResearchVariantsResponse>("/vehicles/spec-drafts/catalog-variants/", {
    params: { model_url: modelUrl },
  });
  return data;
}

export async function createSpecDraft(
  payload: VehicleSpecDraftCreatePayload,
): Promise<VehicleSpecDraft> {
  const { data } = await apiClient.post<VehicleSpecDraft>("/vehicles/spec-drafts/", payload);
  return data;
}

export async function fetchSpecDraft(id: number): Promise<VehicleSpecDraft> {
  const { data } = await apiClient.get<VehicleSpecDraft>(`/vehicles/spec-drafts/${id}/`);
  return data;
}

export async function patchSpecDraft(
  id: number,
  payload: VehicleSpecDraftApprovalPayload,
): Promise<VehicleSpecDraft> {
  const { data } = await apiClient.patch<VehicleSpecDraft>(`/vehicles/spec-drafts/${id}/`, payload);
  return data;
}
