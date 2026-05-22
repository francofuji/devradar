const STATUS_COLORS = {
  WARM: "badge--amber",
  QUALIFIED: "badge--green",
  DISCOVERED: "badge--gray",
  PROFILED: "badge--blue",
  MONITORED: "badge--indigo",
  OUTREACHED: "badge--copper",
  ENGAGED: "badge--green",
  CLOSED: "badge--slate",
  connected: "badge--green",
  connecting: "badge--amber",
  reconnecting: "badge--amber",
  disconnected: "badge--gray",
  ok: "badge--green",
  degraded: "badge--amber",
};

export default function Badge({ children, tone = "gray" }) {
  const resolvedTone = STATUS_COLORS[tone] || `badge--${tone}` || "badge--gray";
  return <span className={`badge ${resolvedTone}`}>{children}</span>;
}
