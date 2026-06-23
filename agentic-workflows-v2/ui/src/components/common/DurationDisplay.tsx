interface Props {
  readonly ms: number | null | undefined;
  readonly className?: string;
}

export default function DurationDisplay({ ms, className = "" }: Readonly<Props>) {
  if (ms == null) return <span className={`tabular-nums ${className}`}>--</span>;

  let display: string;
  if (ms < 1000) {
    display = `${Math.round(ms)}ms`;
  } else if (ms < 60_000) {
    display = `${(ms / 1000).toFixed(1)}s`;
  } else {
    const minutes = Math.floor(ms / 60_000);
    const seconds = ((ms % 60_000) / 1000).toFixed(0);
    display = `${minutes}m ${seconds}s`;
  }

  return <span className={`tabular-nums ${className}`}>{display}</span>;
}
