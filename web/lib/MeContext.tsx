"use client";

import { createContext, useContext } from "react";
import type { Me } from "./types";

export type MeContextValue = { me: Me; token: string };

const MeContext = createContext<MeContextValue | null>(null);

export const MeProvider = MeContext.Provider;

export function useMeContext(): MeContextValue {
  const ctx = useContext(MeContext);
  if (!ctx) throw new Error("useMeContext() must be used inside app/h/[token]/layout.tsx");
  return ctx;
}
