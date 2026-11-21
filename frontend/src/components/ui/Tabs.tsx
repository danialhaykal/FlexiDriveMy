import { Children, createContext, isValidElement, useContext, useId } from "react";
import type { KeyboardEvent, ReactElement, ReactNode } from "react";
import { cn } from "./cn";
import { Select } from "./Select";

// Minimal accessible tabs primitive (role="tablist"/"tab"/"tabpanel",
// roving tabindex, Left/Right arrow-key navigation - Up/Down/Home/End for a
// vertical list (redesign UI-6a: Policy Configuration's section list)) - a shared primitive
// rather than one-off tab styling per screen. Panels for non-active tabs
// unmount rather than hide, so a panel that fetches its own data (e.g.
// F006's TCO tab) naturally only fetches once actually selected.
//
// Usage:
// <Tabs value={tab} onChange={setTab}>
//   <Tabs.List aria-label="Comparison views">
//     <Tabs.Tab value="financing">Financing Pathways</Tabs.Tab>
//     <Tabs.Tab value="tco">TCO Breakdown</Tabs.Tab>
//   </Tabs.List>
//   <Tabs.Panel value="financing">...</Tabs.Panel>
//   <Tabs.Panel value="tco">...</Tabs.Panel>
// </Tabs>

interface TabsContextValue {
  value: string;
  onChange: (value: string) => void;
  idPrefix: string;
}

const TabsContext = createContext<TabsContextValue | null>(null);
// Set by Tabs.List; a vertical list styles its tabs as a side list.
const OrientationContext = createContext<"horizontal" | "vertical">("horizontal");

function useTabsContext(componentName: string): TabsContextValue {
  const context = useContext(TabsContext);
  if (!context) {
    throw new Error(`${componentName} must be rendered inside <Tabs>`);
  }
  return context;
}

interface TabsProps {
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
  className?: string;
}

function Root({ value, onChange, children, className }: TabsProps) {
  const idPrefix = useId();
  return (
    <TabsContext.Provider value={{ value, onChange, idPrefix }}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  );
}

interface TabsListProps {
  children: ReactNode;
  "aria-label": string;
  orientation?: "horizontal" | "vertical";
  // Redesign UI-6c: when given (horizontal lists only), below sm (640 px) the
  // strip is replaced by a labelled <select> with the same options, driving the
  // same state; from sm up the strip shows exactly as before.
  mobileSelectLabel?: string;
}

// A tab's text for the select: the strings inside it (an icon contributes none).
function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement(node)) return textOf((node.props as { children?: ReactNode }).children);
  return "";
}

function List({ children, orientation = "horizontal", mobileSelectLabel, ...rest }: TabsListProps) {
  const context = useContext(TabsContext);
  if (orientation === "vertical") {
    return (
      <OrientationContext.Provider value="vertical">
        <div role="tablist" aria-orientation="vertical" className="flex flex-col gap-0.5" {...rest}>
          {children}
        </div>
      </OrientationContext.Provider>
    );
  }
  // QA audit M9: 5 fixed-padding tabs (Financing/TCO/AI/Affordability/
  // Total-Loss) don't fit a 375px viewport, and a bare flex row has
  // nowhere to put the overflow - it just forces the whole PAGE wider.
  // Scrolling the tablist itself (overflow-x-auto + flex-nowrap, each
  // tab shrink-0 so it keeps its own width rather than getting squashed)
  // keeps every tab reachable via a horizontal swipe/scroll without
  // resizing the page around it - chosen over a dropdown/accordion
  // variant because the tabs stay visually identical to desktop (same
  // component, no separate narrow-viewport UI to maintain) and a swipe
  // is the platform-native gesture for "more tabs than fit" on mobile
  // (matches how native iOS/Android tab bars behave). The scrollbar itself
  // is hidden (scrollbar-none, index.css); the row still scrolls.
  //
  // Redesign UI-6c: a list given `mobileSelectLabel` shows a select instead below
  // sm, so nothing scrolls sideways on a phone (used by the compare page).
  const strip = (
    <div
      role="tablist"
      className={cn(
        "scrollbar-none flex-nowrap gap-1 overflow-x-auto border-b border-border",
        mobileSelectLabel ? "hidden sm:flex" : "flex",
      )}
      {...rest}
    >
      {children}
    </div>
  );
  if (!mobileSelectLabel || !context) return strip;
  const options = Children.toArray(children)
    .filter((child): child is ReactElement<TabProps> => isValidElement(child))
    .map((child) => ({ value: child.props.value, label: textOf(child.props.children).trim() }));
  return (
    <>
      <div className="sm:hidden">
        <Select
          label={mobileSelectLabel}
          value={context.value}
          onChange={(event) => context.onChange(event.target.value)}
          options={options}
        />
      </div>
      {strip}
    </>
  );
}

interface TabProps {
  value: string;
  children: ReactNode;
}

function Tab({ value, children }: TabProps) {
  const { value: activeValue, onChange, idPrefix } = useTabsContext("Tabs.Tab");
  const orientation = useContext(OrientationContext);
  const isSelected = value === activeValue;
  const tabId = `${idPrefix}-tab-${value}`;
  const panelId = `${idPrefix}-panel-${value}`;

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const [prevKey, nextKey] = orientation === "vertical" ? ["ArrowUp", "ArrowDown"] : ["ArrowLeft", "ArrowRight"];
    const isEdgeKey = orientation === "vertical" && (event.key === "Home" || event.key === "End");
    if (event.key !== nextKey && event.key !== prevKey && !isEdgeKey) return;
    const list = event.currentTarget.closest('[role="tablist"]');
    if (!list) return;
    event.preventDefault();
    const tabs = Array.from(list.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
    const currentIndex = tabs.indexOf(event.currentTarget);
    const nextIndex =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? tabs.length - 1
          : event.key === nextKey
            ? (currentIndex + 1) % tabs.length
            : (currentIndex - 1 + tabs.length) % tabs.length;
    const nextTab = tabs[nextIndex];
    nextTab?.focus();
    nextTab?.click();
  };

  return (
    <button
      type="button"
      role="tab"
      id={tabId}
      aria-selected={isSelected}
      aria-controls={panelId}
      tabIndex={isSelected ? 0 : -1}
      onClick={() => onChange(value)}
      onKeyDown={handleKeyDown}
      className={cn(
        orientation === "vertical"
          ? cn(
              "flex w-full items-center gap-2.5 rounded-control px-3 py-2 text-left text-small transition-colors",
              isSelected ? "bg-primary-50 font-semibold text-primary-700" : "font-medium text-ink-muted hover:bg-surface-subtle hover:text-ink",
            )
          : cn(
              // Redesign UI-6c: tighter until lg so the compare page's five tabs fit from 640 px up.
              "-mb-px shrink-0 whitespace-nowrap border-b-2 px-2.5 py-2.5 text-small transition-colors lg:px-3 xl:px-4",
              isSelected
                ? "border-primary-600 font-semibold text-primary-700"
                : "border-transparent font-medium text-ink-muted hover:border-border-strong hover:text-ink",
            ),
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary-500",
      )}
    >
      {children}
    </button>
  );
}

interface TabPanelProps {
  value: string;
  children: ReactNode;
  className?: string;
}

function Panel({ value, children, className }: TabPanelProps) {
  const { value: activeValue, idPrefix } = useTabsContext("Tabs.Panel");
  if (value !== activeValue) return null;

  return (
    <div
      role="tabpanel"
      id={`${idPrefix}-panel-${value}`}
      aria-labelledby={`${idPrefix}-tab-${value}`}
      tabIndex={0}
      className={className}
    >
      {children}
    </div>
  );
}

export const Tabs = Object.assign(Root, { List, Tab, Panel });
