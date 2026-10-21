/**
 * Minimal SVG sparkline. Gaps (null) break the line instead of being drawn as
 * zero. Renders nothing when there is no history — never a placeholder line.
 */
export function Sparkline({
  values,
  width = 96,
  height = 28,
  className,
}: {
  values: (number | null)[];
  width?: number;
  height?: number;
  className?: string;
}) {
  const nums = values.filter((v): v is number => v != null);
  if (nums.length < 2) return null;
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const span = max - min || 1;
  const step = (width - 6) / (values.length - 1);
  const x = (i: number) => 3 + i * step;
  const y = (v: number) => height - 3 - ((v - min) / span) * (height - 6);

  const segments: string[] = [];
  let current = "";
  values.forEach((v, i) => {
    if (v == null) {
      if (current) segments.push(current);
      current = "";
      return;
    }
    current += `${current ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
  });
  if (current) segments.push(current);

  const lastIdx = values.length - 1;
  const last = values[lastIdx];

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={className} aria-hidden>
      {segments.map((d, i) => (
        <path key={i} d={d} fill="none" stroke="var(--subtle-foreground)" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
      ))}
      {last != null && <circle cx={x(lastIdx)} cy={y(last)} r={2.75} fill="var(--primary)" />}
    </svg>
  );
}
