import { formatDateTime, formatRelative } from '../format';
import type { Incident } from '../types';

export type Mode = 'live' | 'replay';

interface Props {
  mode: Mode;
  playing: boolean;
  speed: number;
  cursor: number;
  times: number[];
  incident: Incident | null;
  onTogglePlay: () => void;
  onStep: (delta: number) => void;
  onSeek: (index: number) => void;
  onSpeed: (speed: number) => void;
  onRestart: () => void;
}

export const SPEEDS = [1, 2, 4, 8];

export function ReplayControls(props: Props) {
  const { mode, playing, speed, cursor, times, incident } = props;
  const n = times.length;

  return (
    <div className="controls">
      <div className="controls__buttons">
        <button
          className="icon-btn"
          onClick={props.onRestart}
          disabled={!incident}
          title="Rewind to just before the incident"
          aria-label="Rewind to incident"
        >
          <svg viewBox="0 0 16 16">
            <path d="M3 3h2v10H3zM13 3v10L6 8z" />
          </svg>
        </button>
        <button
          className="icon-btn"
          onClick={() => props.onStep(-1)}
          title="Back 1 minute (←)"
          aria-label="Back one minute"
        >
          <svg viewBox="0 0 16 16">
            <path d="M11 3v10L4 8z" />
          </svg>
        </button>
        <button
          className="icon-btn icon-btn--primary"
          onClick={props.onTogglePlay}
          title={playing ? 'Pause (space)' : 'Play (space)'}
          aria-label={playing ? 'Pause' : 'Play'}
        >
          {playing ? (
            <svg viewBox="0 0 16 16">
              <path d="M4 3h3v10H4zM9 3h3v10H9z" />
            </svg>
          ) : (
            <svg viewBox="0 0 16 16">
              <path d="M5 3v10l8-5z" />
            </svg>
          )}
        </button>
        <button
          className="icon-btn"
          onClick={() => props.onStep(1)}
          title="Forward 1 minute (→)"
          aria-label="Forward one minute"
        >
          <svg viewBox="0 0 16 16">
            <path d="M5 3v10l7-5z" />
          </svg>
        </button>
      </div>

      <input
        className="controls__slider"
        type="range"
        min={0}
        max={n - 1}
        value={cursor}
        onChange={(e) => props.onSeek(Number(e.target.value))}
        aria-label="Replay position"
      />

      <div className="controls__time">
        <strong>{formatDateTime(times[cursor])}</strong>
        <span>
          {mode === 'live'
            ? 'live · latest minute'
            : incident
              ? formatRelative(cursor - incident.start) + ' from incident'
              : 'replay'}
        </span>
      </div>

      <div className="segmented" role="group" aria-label="Replay speed">
        {SPEEDS.map((s) => (
          <button
            key={s}
            className={s === speed ? 'is-active' : ''}
            onClick={() => props.onSpeed(s)}
          >
            {s}×
          </button>
        ))}
      </div>
    </div>
  );
}
