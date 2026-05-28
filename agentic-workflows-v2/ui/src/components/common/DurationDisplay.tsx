interface Props {
  ms: number | null | undefined;
  className?: string;
}

export default function DurationDisplay({ ms, className = "" }: Props) {
  if (ms == null) return <span className={className}>--</span>;

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

  return <span className={className}>{display}</span>;
}
