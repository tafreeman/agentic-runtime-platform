interface BSparkProps {
  values: number[];
  color?: string; // CSS color (var or hex)
  height?: number;
  className?: string;
}

export default function BSpark({
  values,
  color = "rgb(var(--b-green))",
  height = 24,
  className = "",
}: BSparkProps) {
  if (values.length < 2) {
    return <svg height={height} className={className} />;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const width = 100; // viewBox units, scales via preserveAspectRatio=none
  const step = width / (values.length - 1);
  const points = values
    .map((v, i) => {
      const x = i * step;
      const y = height - ((v - min) / range) * (height - 2) - 1;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      width="100%"
      height={height}
      className={className}
    >
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
