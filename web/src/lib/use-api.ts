"use client";

import {
  useQuery,
  useMutation,
  type UseQueryOptions,
  type UseQueryResult,
  type UseMutationOptions,
  type UseMutationResult,
  type QueryKey,
} from "@tanstack/react-query";
import { api, ApiError, type RequestOptions } from "./api-client";

export interface ApiQueryConfig<TData> {
  queryKey: QueryKey;
  endpoint: string;
  params?: Record<string, string | number | boolean | undefined | null>;
  queryOptions?: Omit<UseQueryOptions<TData, ApiError, TData, QueryKey>, "queryKey" | "queryFn">;
  requestOptions?: Omit<RequestOptions, "params">;
}

export function useApiQuery<TData = unknown>({
  queryKey,
  endpoint,
  params,
  queryOptions,
  requestOptions,
}: ApiQueryConfig<TData>): UseQueryResult<TData, ApiError> {
  return useQuery<TData, ApiError, TData, QueryKey>({
    queryKey,
    queryFn: () => api.get<TData>(endpoint, params, requestOptions),
    ...queryOptions,
  });
}

export type MutationMethod = "POST" | "PUT" | "PATCH" | "DELETE";

export interface ApiMutationConfig<TData, TVariables> {
  endpoint: string | ((variables: TVariables) => string);
  method?: MutationMethod;
  mutationOptions?: UseMutationOptions<TData, ApiError, TVariables>;
  requestOptions?: Omit<RequestOptions, "body">;
}

export function useApiMutation<TData = unknown, TVariables = unknown>({
  endpoint,
  method = "POST",
  mutationOptions,
  requestOptions,
}: ApiMutationConfig<TData, TVariables>): UseMutationResult<TData, ApiError, TVariables> {
  return useMutation<TData, ApiError, TVariables>({
    mutationFn: async (variables: TVariables) => {
      const targetEndpoint =
        typeof endpoint === "function" ? endpoint(variables) : endpoint;

      switch (method) {
        case "POST":
          return api.post<TData>(targetEndpoint, variables, requestOptions);
        case "PUT":
          return api.put<TData>(targetEndpoint, variables, requestOptions);
        case "PATCH":
          return api.patch<TData>(targetEndpoint, variables, requestOptions);
        case "DELETE":
          return api.delete<TData>(targetEndpoint, requestOptions);
        default:
          return api.post<TData>(targetEndpoint, variables, requestOptions);
      }
    },
    ...mutationOptions,
  });
}
