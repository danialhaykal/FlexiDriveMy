import type { ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { cn } from "./cn";
import { numeric } from "./tokens";

// Compound table primitive. Pass `numeric` on a HeaderCell/Cell for
// currency/number columns - it right-aligns and applies tabular-nums so
// RM figures line up cleanly down the column. Scrolls horizontally on
// narrow viewports instead of breaking the layout.
//
// Usage:
// <Table>
//   <Table.Head>
//     <Table.Row>
//       <Table.HeaderCell>Pathway</Table.HeaderCell>
//       <Table.HeaderCell numeric>Monthly (RM)</Table.HeaderCell>
//     </Table.Row>
//   </Table.Head>
//   <Table.Body>
//     <Table.Row>
//       <Table.Cell>Hire Purchase</Table.Cell>
//       <Table.Cell numeric>5,344.44</Table.Cell>
//     </Table.Row>
//   </Table.Body>
// </Table>

// Run 2 fix batch 3 (phone layout): below 640px the type is one step smaller and
// the cell padding tighter (3px a side - Run 3 fix batch 5, F-30d: 4px left the Macan
// Electric's and the Alphard's pathway table 5px too wide), so a four-column table such as
// the pathway comparison fits a 390px phone without swiping (a cell that must keep a figure on one line,
// like the pathway table's, says so itself with whitespace-nowrap). From 640px up
// nothing changes. overflow-x-auto stays as the fallback for a table that is still
// too wide (e.g. a seven-figure price, or an admin table with many columns).
// `relative`: a visually hidden header label (sr-only, absolutely positioned) is
// then placed inside this scroll box - without it, a table wider than the
// window pushed that label past the page's edge and widened the whole page.
function Root({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className="relative overflow-x-auto">
      <table className={cn("w-full border-collapse text-caption sm:text-small", className)}>{children}</table>
    </div>
  );
}

function Head({ children }: { children: ReactNode }) {
  return <thead className="border-b border-border text-caption text-ink-muted">{children}</thead>;
}

function Body({ children }: { children: ReactNode }) {
  return <tbody className="divide-y divide-border">{children}</tbody>;
}

// `className` e.g. to mute an archived row in an admin list.
function Row({ children, className }: { children: ReactNode; className?: string }) {
  return <tr className={className}>{children}</tr>;
}

interface HeaderCellProps extends ThHTMLAttributes<HTMLTableCellElement> {
  numeric?: boolean;
}

// Headers are sentence case (as written), 12 px semibold muted - no
// upper-casing, so a car name or "Pathway" keeps its own case.
function HeaderCell({ numeric: isNumeric = false, className, children, ...rest }: HeaderCellProps) {
  return (
    <th
      data-numeric={isNumeric || undefined}
      className={cn(
        "px-[3px] py-2.5 font-semibold sm:px-4",
        isNumeric ? cn("text-right", numeric) : "text-left",
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  );
}

interface CellProps extends TdHTMLAttributes<HTMLTableCellElement> {
  numeric?: boolean;
}

function Cell({ numeric: isNumeric = false, className, children, ...rest }: CellProps) {
  return (
    <td
      data-numeric={isNumeric || undefined}
      className={cn(
        "px-[3px] py-3.5 text-ink sm:px-4",
        isNumeric ? cn("text-right font-medium", numeric) : "text-left",
        className,
      )}
      {...rest}
    >
      {children}
    </td>
  );
}

export const Table = Object.assign(Root, { Head, Body, Row, HeaderCell, Cell });
