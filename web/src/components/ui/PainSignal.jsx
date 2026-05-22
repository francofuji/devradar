import Badge from "./Badge";

const CATEGORY_TONE = {
  api_cost: "red",
  scaling: "copper",
  reliability: "amber",
  auth: "indigo",
  observability: "blue",
};

export default function PainSignal({ signal }) {
  const tone = CATEGORY_TONE[signal.pain_category] || "gray";

  return (
    <div className="pain-signal">
      <div className="pain-signal__header">
        <Badge tone={tone}>{signal.pain_category || "unknown"}</Badge>
        {signal.confidence < 0.7 && (
          <Badge tone="gray">Low confidence</Badge>
        )}
        {signal.confidence != null && (
          <span className="pain-signal__conf">{Math.round(signal.confidence * 100)}%</span>
        )}
      </div>
      {signal.description && (
        <p className="pain-signal__desc">{signal.description}</p>
      )}
      {signal.evidence && (
        <blockquote className="pain-signal__evidence">{signal.evidence}</blockquote>
      )}
    </div>
  );
}
