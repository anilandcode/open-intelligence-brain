/** Date helpers for <input type="date">, which speaks YYYY-MM-DD in local time. */

export function addDays(days: number, from = new Date()): Date {
  return new Date(from.getTime() + days * 86_400_000);
}

export function dateInput(value: Date | string | null | undefined): string {
  if (!value) return "";
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 10);
}

/** "" means "no date" and is sent as null so the API clears it. */
export function fromDateInput(value: string): string | null {
  return value ? `${value}T00:00:00Z` : null;
}

export function shortDate(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
