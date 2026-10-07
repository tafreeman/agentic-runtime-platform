import { useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { MoreHorizontal, X } from "lucide-react";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "../ui/sheet";
import { NAV_ITEMS, isNavItemActive } from "./navigation";

const PRIMARY_ITEMS = NAV_ITEMS.filter((item) => item.mobilePrimary);

// Bottom-bar cells are the full 56px bar height (≥44px touch target).
const BAR_ITEM =
  "relative flex min-h-11 flex-col items-center justify-center gap-0.5 px-1 text-micro font-medium transition-colors focus-ring-inset";
const BAR_ACTIVE = "text-el-ink";
const BAR_INACTIVE = "text-el-muted hover:text-el-ink";

/** Top rule marking the current destination (not colour alone: also aria-current). */
function BarRail() {
  return (
    <span
      aria-hidden="true"
      className="absolute inset-x-3 top-0 h-0.5 bg-el-accent-strong"
    />
  );
}

/**
 * Mobile bottom navigation (<md): the four most-used destinations plus a
 * labelled "More" control that opens a bottom Sheet listing every destination,
 * so all of them stay reachable on a phone.
 */
export default function MobileNav() {
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  // Set when the sheet closes because a destination was picked: focus then
  // follows the route change into <main> instead of returning to "More".
  const navigatedRef = useRef(false);

  // The current destination when it is only reachable through "More".
  const overflowCurrent = NAV_ITEMS.find(
    (item) => !item.mobilePrimary && isNavItemActive(item, pathname),
  );
  const overflowActive = overflowCurrent !== undefined;

  const handleCloseAutoFocus = (event: Event) => {
    if (!navigatedRef.current) return; // Escape / close / overlay: Radix restores focus to "More".
    navigatedRef.current = false;
    const main = document.getElementById("main-content");
    if (main) {
      event.preventDefault();
      main.focus();
    }
  };

  return (
    <nav
      aria-label="Mobile navigation"
      className="fixed inset-x-0 bottom-9 z-40 grid h-14 grid-cols-5 border-t border-el-divider bg-el-raised md:hidden"
    >
      {PRIMARY_ITEMS.map((item) => {
        const active = isNavItemActive(item, pathname);
        return (
          <Link
            key={item.to}
            to={item.to}
            aria-current={active ? "page" : undefined}
            className={`${BAR_ITEM} ${active ? BAR_ACTIVE : BAR_INACTIVE}`}
          >
            {active && <BarRail />}
            <span className="font-mono text-el-faint" aria-hidden="true">
              {item.num}
            </span>
            <span>{item.shortLabel}</span>
          </Link>
        );
      })}

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <button
            type="button"
            data-testid="mobile-nav-more"
            aria-label={
              overflowCurrent
                ? `More destinations (current: ${overflowCurrent.label})`
                : "More destinations"
            }
            className={`${BAR_ITEM} ${overflowActive ? BAR_ACTIVE : BAR_INACTIVE}`}
          >
            {overflowActive && <BarRail />}
            <MoreHorizontal aria-hidden="true" className="size-4" />
            <span>more</span>
          </button>
        </SheetTrigger>
        <SheetContent
          side="bottom"
          showCloseButton={false}
          aria-describedby={undefined}
          onCloseAutoFocus={handleCloseAutoFocus}
          className="max-h-[85svh] gap-0 rounded-t-lg pb-4"
        >
          <SheetHeader className="flex-row items-center justify-between gap-2 py-2 pr-2 pl-4">
            <SheetTitle className="font-sans text-base font-semibold">
              Go to
            </SheetTitle>
            <SheetClose asChild>
              <button
                type="button"
                aria-label="Close navigation"
                className="grid size-11 place-items-center rounded-md text-el-secondary transition-colors hover:bg-el-hover hover:text-el-ink focus-ring"
              >
                <X aria-hidden="true" className="size-4" />
              </button>
            </SheetClose>
          </SheetHeader>
          <nav aria-label="All destinations" className="overflow-y-auto px-2">
            <ul className="flex flex-col">
              {NAV_ITEMS.map((item) => {
                const active = isNavItemActive(item, pathname);
                return (
                  <li key={item.to}>
                    <Link
                      to={item.to}
                      aria-current={active ? "page" : undefined}
                      onClick={() => {
                        navigatedRef.current = true;
                        setOpen(false);
                      }}
                      className={`relative flex min-h-11 items-center gap-3 rounded-md px-3 text-sm transition-colors focus-ring-inset ${
                        active
                          ? "bg-el-subtle font-medium text-el-ink"
                          : "text-el-secondary hover:bg-el-hover hover:text-el-ink"
                      }`}
                    >
                      {active && (
                        <span
                          aria-hidden="true"
                          className="absolute inset-y-2 left-0 w-0.5 bg-el-accent-strong"
                        />
                      )}
                      <span
                        className="w-5 flex-none font-mono text-micro text-el-faint"
                        aria-hidden="true"
                      >
                        {item.num}
                      </span>
                      <span>{item.label}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
        </SheetContent>
      </Sheet>
    </nav>
  );
}
