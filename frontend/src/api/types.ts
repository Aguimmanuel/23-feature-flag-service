export const environments = ["development", "staging", "production"] as const;
export type Environment = (typeof environments)[number];
export interface Configuration {
  environment: Environment;
  enabled: boolean;
  target_groups: string[];
  rollout_percentage: number;
  version: number;
  updated_at: string;
}
export interface Flag {
  id: string;
  key: string;
  description: string;
  archived: boolean;
  created_at: string;
  updated_at: string;
}
export interface FlagDetail extends Flag {
  environments: Configuration[];
}
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
export interface Decision {
  flag_key: string;
  environment: Environment;
  value: boolean;
  reason:
    | "FLAG_DISABLED"
    | "GROUP_MATCH"
    | "ROLLOUT_INCLUDED"
    | "ROLLOUT_EXCLUDED";
  bucket: number | null;
}
export interface Audit {
  id: string;
  flag_key: string;
  environment: Environment | null;
  action: string;
  actor: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown>;
  created_at: string;
}
export type ConfigInput = Pick<
  Configuration,
  "enabled" | "target_groups" | "rollout_percentage" | "version"
>;
