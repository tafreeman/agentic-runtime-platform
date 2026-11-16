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
    <div className={`rounded-lg border border-el-divider bg-el-surface ${className}`}>
      {title && (
        <div className="flex items-center justify-between rounded-t-lg border-b border-el-divider bg-el-subtle px-3 py-1.5">
          <div className="flex items-center gap-2 text-micro uppercase tracking-[0.5px] text-el-secondary">
            {/* Decorative block mark: neutral ink, not a status color. */}
            <span aria-hidden="true" className="leading-none text-el-faint">
              ▊
            </span>
            <span>{title}</span>
          </div>
          {right && <div className="flex items-center gap-2">{right}</div>}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </div>
  );
}
