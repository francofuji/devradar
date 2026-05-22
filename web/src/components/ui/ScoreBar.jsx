export default function ScoreBar({ value = 0, max = 100, label = "Score" }) {
  const safeValue = Math.max(0, Math.min(value, max));
  const percentage = max === 0 ? 0 : (safeValue / max) * 100;

  return (
    <div className="scorebar">
      <div className="scorebar__meta">
        <span>{label}</span>
        <strong>{safeValue.toFixed(0)}</strong>
      </div>
      <div className="scorebar__track" aria-hidden="true">
        <div className="scorebar__fill" style={{ width: `${percentage}%` }} />
      </div>
    </div>
  );
}
