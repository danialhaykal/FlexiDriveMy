import { apiClient } from "./client";
import { fetchAllPages } from "./allPages";
import type { FullList } from "./allPages";
import type { MLTrainingRun, ProductionModelInfo } from "../types/ml";

// GET /api/ml/training-runs/ (F012, admin-only - apps/ml/views.py::
// MLTrainingRunListView): a paginated {count, next, previous, results}
// envelope (PageNumberPagination, PAGE_SIZE=25). Run 3 fix batch 4 (F-17):
// every page is loaded (api/allPages.ts), so run 26 onward is not dropped.
//
// Server orders -created_at (newest first, see MLTrainingRun.Meta) - this
// function returns exactly that order; a caller wanting chronological
// order (e.g. a trend chart) reverses it itself rather than this function
// silently changing what the API returns.
export async function fetchTrainingRuns(): Promise<FullList<MLTrainingRun>> {
  return fetchAllPages<MLTrainingRun>("/ml/training-runs/");
}

// ML batch 1 - GET /api/ml/production-model/ (ProductionModelView): the
// production card's target and both R² values.
export async function fetchProductionModel(): Promise<ProductionModelInfo> {
  const { data } = await apiClient.get<ProductionModelInfo>("/ml/production-model/");
  return data;
}

// Batch 6B - GET /api/ml/training-runs/<id>/ (MLTrainingRunDetailView).
// Used to poll a single just-uploaded run while it's still
// pending/running, without refetching the whole history list.
export async function fetchTrainingRun(id: number): Promise<MLTrainingRun> {
  const { data } = await apiClient.get<MLTrainingRun>(`/ml/training-runs/${id}/`);
  return data;
}

// Batch 6B - POST /api/ml/datasets/ (MLDatasetUploadView), multipart -
// mirrors adminFleet.ts::bulkImportVehicles's upload pattern exactly.
export async function uploadTrainingDataset(file: File): Promise<MLTrainingRun> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post<MLTrainingRun>("/ml/datasets/", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

// Batch 6B - POST /api/ml/training-runs/<id>/deploy/
// (MLTrainingRunDeployView) - UC012's separate, human-gated "Deploy New
// Model Weights" action.
export async function deployTrainingRun(id: number): Promise<MLTrainingRun> {
  const { data } = await apiClient.post<MLTrainingRun>(`/ml/training-runs/${id}/deploy/`);
  return data;
}
