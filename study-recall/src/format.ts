export function formatClock(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export function countNoun(count: number, singular: string, plural?: string): string {
  return `${count} ${count === 1 ? singular : (plural ?? `${singular}s`)}`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${Math.round(value * 10) / 10}%`;
}

export function formatMarks(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "Review";
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export function statusLabel(status: string): string {
  switch (status) {
    case "well_remembered":
      return "Well remembered";
    case "developing":
      return "Developing";
    case "needs_revision":
      return "Needs revision";
    case "untested":
      return "Not tested yet";
    case "successful":
      return "Recalled successfully";
    case "partial":
      return "Partially recalled";
    case "skipped":
      return "Skipped";
    default:
      return status.replaceAll("_", " ");
  }
}

export function questionLabel(kind: string): string {
  switch (kind) {
    case "fib":
      return "Fill in the blank";
    case "mcq":
      return "Multiple choice";
    case "short":
      return "Short question";
    case "long":
      return "Long question";
    default:
      return kind;
  }
}

export const CONCEPT_KINDS = [
  { id: "definition", label: "Definition" },
  { id: "fact", label: "Key fact" },
  { id: "keyword", label: "Keyword" },
  { id: "formula", label: "Formula" },
  { id: "example", label: "Example" },
  { id: "expected_point", label: "Expected answer point" },
] as const;
