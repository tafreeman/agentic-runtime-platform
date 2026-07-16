"use client"

import { Toaster as Sonner, type ToasterProps } from "sonner"
import { Check, Circle, TriangleAlert, X, Loader2 } from "lucide-react"
import { useTheme } from "../../hooks/useTheme"

const Toaster = ({ ...props }: ToasterProps) => {
  const [theme] = useTheme()

  return (
    <Sonner
      theme={theme === "dark" ? "dark" : "light"}
      className="toaster group"
      icons={{
        success: (
          <Check className="size-4" />
        ),
        info: (
          <Circle className="size-4" />
        ),
        warning: (
          <TriangleAlert className="size-4" />
        ),
        error: (
          <X className="size-4" />
        ),
        loading: (
          <Loader2 className="size-4 animate-spin" />
        ),
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "var(--radius)",
        } as React.CSSProperties
      }
      toastOptions={{
        classNames: {
          toast: "cn-toast",
        },
      }}
      {...props}
    />
  )
}

export { Toaster }
