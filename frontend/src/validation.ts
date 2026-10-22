// Keep identifiers unchanged: reject whitespace instead of silently trimming it.
export function identifier(value: string, max: number) {
  return (
    value.length >= 1 &&
    value.length <= max &&
    value.trim() === value &&
    !/[\x00-\x1f\x7f]/.test(value)
  );
}
export function parseGroups(value: string): string[] {
  const groups = value === "" ? [] : value.split("\n");
  if (
    groups.length > 20 ||
    groups.some((g) => !identifier(g, 64)) ||
    new Set(groups).size !== groups.length
  )
    throw new Error(
      "Use at most 20 unique groups, one per line (1–64 characters, no surrounding whitespace or control characters).",
    );
  return groups;
}
export function parsePercentage(value: string): number {
  if (!/^\d+$/.test(value) || Number(value) > 100)
    throw new Error("Rollout must be a whole number from 0 to 100.");
  return Number(value);
}
