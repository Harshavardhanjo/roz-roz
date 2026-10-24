"use client";

import { useEffect, useState } from "react";
import { ApiError, me as fetchMe } from "./api";
import type { Me } from "./types";

const LAST_TOKEN_KEY = "rozroz:lastToken";

export function rememberToken(token: string): void {
  try {
    window.localStorage.setItem(LAST_TOKEN_KEY, token);
  } catch {
    // localStorage unavailable (private mode, SSR) — not critical, just skip remembering it
  }
}

export function getLastToken(): string | null {
  try {
    return window.localStorage.getItem(LAST_TOKEN_KEY);
  } catch {
    return null;
  }
}

export function useMe(token: string) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchMe(token)
      .then((result) => {
        if (cancelled) return;
        setMe(result);
        rememberToken(token);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err : new ApiError(0, "network_error", String(err)));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, version]);

  return { me, loading, error, reload: () => setVersion((v) => v + 1) };
}
