import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { MoreHorizontal } from "lucide-react";
import { cn } from "../ui/cn";

// A row's actions behind one icon button (redesign UI-6a) - instead of a row
// of solid red buttons. The menu opens below the button, in a layer of its own
// (so a table's scroll container never clips it), and is keyboard operable:
// Enter / Space / ArrowDown open it on the first item, ArrowUp / ArrowDown /
// Home / End move, Escape closes it and returns focus to the button, Tab or a
// click outside closes it. Choosing an item runs the SAME handler the old
// button ran (an archive still goes through its confirm dialog).
//
// Usage: <RowActionsMenu label="Actions for Toyota Camry 2.5V" actions={[
//          { label: "Edit", onSelect: () => openEdit(row) },
//          { label: "Archive", onSelect: () => askArchive(row), tone: "danger" },
//        ]} />

export interface RowAction {
  label: string;
  onSelect: () => void;
  // "danger" for Archive: red text on a quiet background (never a solid red button).
  tone?: "default" | "danger";
}

interface RowActionsMenuProps {
  label: string;
  actions: RowAction[];
}

const MENU_GAP_PX = 4;

export function RowActionsMenu({ label, actions }: RowActionsMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; right: number }>({ top: 0, right: 0 });
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  function close(returnFocus: boolean) {
    setIsOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  }

  function open() {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect) setPosition({ top: rect.bottom + MENU_GAP_PX, right: Math.max(window.innerWidth - rect.right, 8) });
    setIsOpen(true);
  }

  function items(): HTMLButtonElement[] {
    return Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? []);
  }

  // On open: focus the first item.
  useLayoutEffect(() => {
    if (isOpen) items()[0]?.focus();
  }, [isOpen]);

  // A click outside, a scroll or a resize closes the menu (its position would be stale).
  useEffect(() => {
    if (!isOpen) return;
    function onPointerDown(event: MouseEvent) {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      close(false);
    }
    function onScrollOrResize() {
      close(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    window.addEventListener("resize", onScrollOrResize);
    window.addEventListener("scroll", onScrollOrResize, true);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      window.removeEventListener("resize", onScrollOrResize);
      window.removeEventListener("scroll", onScrollOrResize, true);
    };
  }, [isOpen]);

  function onTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "ArrowDown" && !isOpen) {
      event.preventDefault();
      open();
    }
  }

  function onMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const list = items();
    const index = list.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "Escape") {
      event.preventDefault();
      close(true);
    } else if (event.key === "Tab") {
      close(false);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      list[(index + 1) % list.length]?.focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      list[(index - 1 + list.length) % list.length]?.focus();
    } else if (event.key === "Home") {
      event.preventDefault();
      list[0]?.focus();
    } else if (event.key === "End") {
      event.preventDefault();
      list[list.length - 1]?.focus();
    }
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-controls={isOpen ? menuId : undefined}
        onClick={() => (isOpen ? close(false) : open())}
        onKeyDown={onTriggerKeyDown}
        className={cn(
          "inline-flex h-8 w-8 items-center justify-center rounded-control text-ink-muted transition-colors",
          "hover:bg-surface-subtle hover:text-ink",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2",
          isOpen && "bg-surface-subtle text-ink",
        )}
      >
        <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
      </button>
      {isOpen &&
        createPortal(
          <div
            ref={menuRef}
            id={menuId}
            role="menu"
            aria-label={label}
            onKeyDown={onMenuKeyDown}
            style={{ position: "fixed", top: position.top, right: position.right }}
            className="z-50 min-w-[10rem] rounded-control border border-border bg-surface py-1 shadow-lg"
          >
            {actions.map((action) => (
              <button
                key={action.label}
                type="button"
                role="menuitem"
                tabIndex={-1}
                onClick={() => {
                  close(false);
                  action.onSelect();
                }}
                className={cn(
                  "block w-full px-3 py-2 text-left text-small font-medium focus:outline-none",
                  action.tone === "danger"
                    ? "text-danger-700 hover:bg-danger-50 focus:bg-danger-50"
                    : "text-ink hover:bg-surface-subtle focus:bg-surface-subtle",
                )}
              >
                {action.label}
              </button>
            ))}
          </div>,
          document.body,
        )}
    </>
  );
}
