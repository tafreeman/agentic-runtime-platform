import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

/**
 * Invisible ::after overlay centred on the button that is at least 36x36px,
 * so compact controls keep their visual size but meet the desktop hit-target
 * floor. Needs the `relative` (or any non-static) position on the button.
 */
const HIT_AREA =
  "after:absolute after:top-1/2 after:left-1/2 after:size-full after:min-h-9 after:min-w-9 after:-translate-x-1/2 after:-translate-y-1/2"

const buttonVariants = cva(
  "relative inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md border text-sm font-semibold transition-colors duration-150 focus-ring disabled:pointer-events-none disabled:opacity-45 [&_svg]:pointer-events-none [&_svg]:h-4 [&_svg]:w-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "border-primary bg-primary text-primary-foreground hover:bg-el-ink/90",
        outline:
          "border-border bg-transparent text-foreground hover:bg-muted",
        secondary:
          "border-secondary bg-secondary text-secondary-foreground hover:bg-el-hover",
        ghost:
          "border-transparent bg-transparent text-foreground hover:bg-muted",
        // destructive-foreground is the raised surface, so the label stays
        // AA on the danger fill in both themes (white failed on dark salmon).
        destructive:
          "border-destructive bg-destructive text-destructive-foreground hover:bg-destructive/90",
        link: "border-transparent text-primary underline-offset-4 hover:underline",
      },
      // Compact sizes stay visually small but get a >=36x36px hit area
      // (design system §10.1/§16) from a centred ::after overlay.
      size: {
        default: "h-10 px-4",
        xs: `h-7 px-2 text-xs ${HIT_AREA}`,
        sm: `h-8 px-3 text-xs ${HIT_AREA}`,
        lg: "h-11 px-5",
        icon: "h-10 w-10 p-0",
        "icon-xs": `h-7 w-7 p-0 ${HIT_AREA}`,
        "icon-sm": `h-8 w-8 p-0 ${HIT_AREA}`,
        "icon-lg": "h-11 w-11 p-0",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
