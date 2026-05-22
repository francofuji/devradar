import { Link } from "react-router-dom";
import Badge from "./Badge";
import ScoreBar from "./ScoreBar";
import { formatDaysAgo, formatScore, formatTrajectory, formatArchetype } from "../../utils/formatters";

const TRAJECTORY_COLOR = {
  up: "#4ade80",
  down: "#f87171",
  flat: "#94a3b8",
};

export default function EntityCard({ entity }) {
  const traj = entity.trajectory_direction || "flat";
  const trajColor = TRAJECTORY_COLOR[traj] || TRAJECTORY_COLOR.flat;

  return (
    <article className="panel entity-card">
      <div className="entity-card__header">
        <div className="entity-card__identity">
          <Link to={`/entities/${entity.id}`} className="entity-card__handle">
            {entity.name || entity.id}
          </Link>
          {entity.name && entity.id !== entity.name && (
            <span className="entity-card__sub">@{entity.id}</span>
          )}
        </div>
        <div className="panel__badges">
          <Badge tone={entity.status}>{entity.status || "unknown"}</Badge>
          {entity.archetype && entity.archetype !== "unknown" && (
            <Badge tone="indigo">{formatArchetype(entity.archetype)}</Badge>
          )}
        </div>
      </div>

      <div className="entity-card__scores">
        <div className="entity-card__score-row">
          <span>Intent</span>
          <ScoreBar value={entity.intent_score} max={100} label={formatScore(entity.intent_score)} />
        </div>
        <div className="entity-card__score-row">
          <span>Maturity</span>
          <ScoreBar value={entity.maturity_score} max={100} label={formatScore(entity.maturity_score)} />
        </div>
      </div>

      <div className="entity-card__footer">
        <span style={{ color: trajColor }} className="entity-card__traj">
          {formatTrajectory(entity.trajectory_7d)} 7d
        </span>
        <span className="entity-card__age">{formatDaysAgo(entity.last_active)}</span>
      </div>
    </article>
  );
}
