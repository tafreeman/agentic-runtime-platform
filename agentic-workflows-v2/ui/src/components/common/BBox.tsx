import type { ReactNode } from "react";

interface BBoxProps {
  title?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}

export default function BBox({
  title,
  right,
  children,
  className = "",
  bodyClassName = "",
}: BBoxProps) {
  return (
    <div
      className={`rounded-[4px] border border-b-line bg-b-bg1 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)] ${className}`}
    >
      {title && (
        <div className="flex items-center justify-between border-b border-b-line bg-b-bg2 rounded-t-[3px] px-[11px] py-[5px]">
          <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.5px] text-b-text-mid">
            <span className="text-b-green leading-none">▊</span>
            <span>{title}</span>
          </div>
          {right && <div className="flex items-center gap-2">{right}</div>}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </div>
  );
}
