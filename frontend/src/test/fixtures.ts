// Synthetic fixtures are imported by tests only. Release code never imports them.
import type { FlagDetail, Page, Flag } from "../api/types";
export const flag: FlagDetail = {
  id: "9b506c00-76ba-4dc4-ae16-33190fdf9651",
  key: "new-checkout",
  description: "New checkout experiment",
  archived: false,
  created_at: "2026-01-01T12:00:00Z",
  updated_at: "2026-01-01T12:00:00Z",
  environments: ["development", "staging", "production"].map((environment) => ({
    environment: environment as "development" | "staging" | "production",
    enabled: false,
    target_groups: [],
    rollout_percentage: 0,
    version: 1,
    updated_at: "2026-01-01T12:00:00Z",
  })),
};
export const list: Page<Flag> = {
  items: [flag],
  total: 1,
  limit: 50,
  offset: 0,
};
export const empty = { items: [], total: 0, limit: 50, offset: 0 };
export const evaluation = {
  flag_key: flag.key,
  environment: "development",
  value: false,
  reason: "FLAG_DISABLED",
  bucket: null,
};
export const errorBody = (code: string, message: string) => ({
  error: { code, message, details: [] },
});
