import { useQuery } from "@tanstack/react-query";
import { listDatasetSamples, getDatasetSampleDetail } from "../api/client";
import type { DatasetSampleListResponse, DatasetSampleDetailResponse } from "../api/types";

export function useDatasetSamples(
  datasetSource: string | null,
  datasetId: string | null,
  offset = 0,
  limit = 20
) {
  return useQuery<DatasetSampleListResponse>({
    queryKey: ["dataset-samples", datasetSource, datasetId, offset, limit],
    queryFn: () => listDatasetSamples(datasetSource!, datasetId!, offset, limit),
    enabled: !!datasetSource && !!datasetId,
  });
}

export function useDatasetSampleDetail(
  datasetSource: string | null,
  datasetId: string | null,
  sampleIndex: number | null
) {
  return useQuery<DatasetSampleDetailResponse>({
    queryKey: ["dataset-sample-detail", datasetSource, datasetId, sampleIndex],
    queryFn: () => getDatasetSampleDetail(datasetSource!, datasetId!, sampleIndex!),
    enabled: !!datasetSource && !!datasetId && sampleIndex !== null,
  });
}
