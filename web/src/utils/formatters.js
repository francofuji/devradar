export function formatScore(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "0";
  }
  return Number(value).toFixed(0);
}

export function formatTier(value) {
  if (!value) {
    return "Unclassified";
  }
  return String(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function formatDaysAgo(value) {
  if (!value) {
    return "n/a";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "n/a";
  }
  const days = Math.max(0, Math.floor((Date.now() - date.getTime()) / 86400000));
  if (days === 0) {
    return "today";
  }
  if (days === 1) {
    return "1 day ago";
  }
  return `${days} days ago`;
}

export function formatTrajectory(value) {
  const numeric = Number(value || 0);
  if (numeric > 0) {
    return `↑ ${numeric.toFixed(1)}`;
  }
  if (numeric < 0) {
    return `↓ ${Math.abs(numeric).toFixed(1)}`;
  }
  return "→ 0.0";
}

export function formatArchetype(value) {
  return formatTier(value || "unknown");
}
