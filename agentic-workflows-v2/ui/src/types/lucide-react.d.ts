/**
 * Type declarations for lucide-react.
 *
 * lucide-react@1.16.0 ships without its .d.ts files due to a broken publish.
 * This shim provides typed exports for all icons used in this project so that
 * the TypeScript build succeeds without downgrading the package.
 */
declare module "lucide-react" {
  import { FC, SVGProps } from "react";

  export interface LucideProps extends SVGProps<SVGSVGElement> {
    size?: number | string;
    strokeWidth?: number | string;
    absoluteStrokeWidth?: boolean;
    color?: string;
  }

  export type LucideIcon = FC<LucideProps>;

  export const ArrowLeft: LucideIcon;
  export const ArrowRight: LucideIcon;
  export const Check: LucideIcon;
  export const CheckCircle2: LucideIcon;
  export const Command: LucideIcon;
  export const CornerDownLeft: LucideIcon;
  export const Search: LucideIcon;
  export const Terminal: LucideIcon;
  export const ChevronDown: LucideIcon;
  export const ChevronRight: LucideIcon;
  export const Circle: LucideIcon;
  export const Clock: LucideIcon;
  export const Copy: LucideIcon;
  export const Cpu: LucideIcon;
  export const Database: LucideIcon;
  export const ExternalLink: LucideIcon;
  export const Gauge: LucideIcon;
  export const HardDrive: LucideIcon;
  export const LayoutDashboard: LucideIcon;
  export const Lightbulb: LucideIcon;
  export const List: LucideIcon;
  export const Loader2: LucideIcon;
  export const Pencil: LucideIcon;
  export const Play: LucideIcon;
  export const Plus: LucideIcon;
  export const Radio: LucideIcon;
  export const RotateCcw: LucideIcon;
  export const Save: LucideIcon;
  export const Settings2: LucideIcon;
  export const SlidersHorizontal: LucideIcon;
  export const Timer: LucideIcon;
  export const TriangleAlert: LucideIcon;
  export const Trophy: LucideIcon;
  export const Workflow: LucideIcon;
  export const X: LucideIcon;
}
