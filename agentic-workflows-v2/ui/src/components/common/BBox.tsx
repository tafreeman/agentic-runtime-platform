import type { ReactNode } from "react";

interface BBoxProps {
  readonly title?: string;
  readonly right?: ReactNode;
  readonly children: ReactNode;
  readonly className?: string;
  readonly bodyClassName?: string;
}

export default function BBox({
  title,
  right,
  children,
  className = "",
  bodyClassName = "",
}: Readonly<BBoxProps>) {
  return (
    <div
      className={`border-b-line bg-b-bg1 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)] ${className}`}
      style={{ borderRadius: "var(--b-rad-lg)", borderWidth: "var(--b-bw)", borderStyle: "solid" }}
    >
      {title && (
        <div
          className="flex items-center justify-between border-b border-b-line bg-b-bg2 px-[11px] py-[5px]"
          style={{
            borderTopLeftRadius: "var(--b-rad-lg)",
            borderTopRightRadius: "var(--b-rad-lg)",
          }}
        >
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.5px] text-b-text-mid">
            <span className="text-b-green leading-none">▊</span>
            <span style={{ fontFamily: "var(--b-font-heading)" }}>{title}</span>
          </div>
          {right && <div className="flex items-center gap-2">{right}</div>}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </div>
  );
}
