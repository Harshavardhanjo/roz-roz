"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "./api";

// Small fetch-on-mount hook shared by the dashboard/payments/votes/audit pages.
// No caching layer (SWR/React Query) by design — this app is small enough that a
// plain useEffect + manual reload() covers every page here.
export function useApi<T>(fn: () => Promise<T>, deps: unknown[]): {
  data: T | null;
  loading: boolean;
  error: ApiError | null;
  reload: () => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [version, setVersion] = useState(0);

  const stableFn = useCallback(fn, deps); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    stableFn()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err : new ApiError(0, "network_error", String(err)));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [stableFn, version]);

  return { data, loading, error, reload: () => setVersion((v) => v + 1) };
}
