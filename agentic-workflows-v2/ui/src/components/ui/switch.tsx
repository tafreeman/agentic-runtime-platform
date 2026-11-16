import * as React from "react"
import { Switch as SwitchPrimitive } from "radix-ui"

import { cn } from "@/lib/utils"

function Switch({
  className,
  size = "default",
  ...props
}: React.ComponentProps<typeof SwitchPrimitive.Root> & {
  size?: "sm" | "default"
}) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      data-size={size}
      // Track and thumb use theme-flipping tokens: the unchecked track is
      // ink-faint (>=4.5:1 to the raised thumb and the surface; the old
      // divider track was ~1.8:1). The ::after overlay gives a >=36px target.
      className={cn(
        "peer group/switch relative inline-flex shrink-0 items-center rounded-full border border-transparent transition-colors after:absolute after:-inset-3 focus-ring aria-invalid:border-destructive data-[size=default]:h-[18.4px] data-[size=default]:w-[32px] data-[size=sm]:h-[14px] data-[size=sm]:w-[24px] data-checked:bg-primary data-unchecked:bg-el-faint data-disabled:cursor-not-allowed data-disabled:opacity-50",
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className="pointer-events-none block rounded-full bg-el-raised ring-0 transition-transform group-data-[size=default]/switch:size-4 group-data-[size=sm]/switch:size-3 data-checked:group-data-[size=default]/switch:translate-x-[calc(100%-2px)] data-checked:group-data-[size=sm]/switch:translate-x-[calc(100%-2px)] data-unchecked:group-data-[size=default]/switch:translate-x-0 data-unchecked:group-data-[size=sm]/switch:translate-x-0"
      />
    </SwitchPrimitive.Root>
  )
}

export { Switch }
