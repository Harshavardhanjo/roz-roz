// Server-only proxy: the backend's admin token must never reach the browser.
// Calls the real backend's POST /api/admin/reset-demo with X-Admin-Token, set only here.

import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function POST() {
  const adminToken = process.env.ADMIN_TOKEN;
  if (!adminToken) {
    return NextResponse.json(
      { error: { code: "admin_token_not_configured", message: "Set ADMIN_TOKEN in the web app's server environment" } },
      { status: 500 }
    );
  }

  const res = await fetch(`${BACKEND_URL}/api/admin/reset-demo`, {
    method: "POST",
    headers: { "X-Admin-Token": adminToken },
  });

  const body = await res.json();
  return NextResponse.json(body, { status: res.status });
}
