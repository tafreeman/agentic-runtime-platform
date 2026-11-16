import { clsx, type ClassValue } from "clsx"
import { extendTailwindMerge } from "tailwind-merge"

// `text-micro` is a custom font size (@theme `--text-micro`, the 11px type
// floor). Register it on the `text` scale, otherwise tailwind-merge reads it
// as a text *color* and `cn("text-el-ink", "text-micro")` drops the color.
const twMerge = extendTailwindMerge({
  extend: { theme: { text: ["micro"] } },
})

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
