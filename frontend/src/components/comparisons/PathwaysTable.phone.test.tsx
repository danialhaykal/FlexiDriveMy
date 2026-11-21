import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { PathwaysTable } from "./PathwaysTable";
import { Table } from "../ui/Table";
import type { ComparisonResult } from "../../types/comparisons";

// The pathways on a phone (redesign UI-3). The pathway TABLE - and with it the
// 3 px phone-padding rule that squeezed its four columns into 390 px - is gone:
// each pathway is now a card in a one-column grid below lg (three columns from
// lg), so nothing scrolls sideways and no figure is squeezed. jsdom does no
// layout, so this pins the structure that makes that work; the real widths are
// measured in a 390 px browser frame.

const COMPARISON: ComparisonResult = {
  vehicle_id: 5, tenure_months: 60, mileage_band: "standard", downpayment: "26780.00",
  hire_purchase: {
    monthly_instalment: "4579.38", upfront_cash: "26780.00", total_contract_outlay: "301542.80",
    interest_rate_percent: "2.8000", effective_rate_percent: "5.2805",
  },
  gfv_leasing: null,
  subscription: null,
  unavailable: { gfv_leasing: "GFV is not available.", subscription: "Subscription plans run for 12, 24 or 36 months." },
} as unknown as ComparisonResult;

describe("PathwaysTable on a phone", () => {
  it("is no longer a table: one card per pathway, in a grid that is one column below lg", () => {
    render(<PathwaysTable comparison={COMPARISON} />);

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const cards = screen.getAllByRole("article");
    expect(cards.map((card) => card.getAttribute("aria-label"))).toEqual(["Hire Purchase", "GFV Leasing", "Subscription"]);
    const grid = cards[0].closest(".grid")!;
    expect(grid).toHaveClass("grid-cols-1", "lg:grid-cols-3");
    expect(grid.className).not.toMatch(/px-\[3px\]/);
  });

  it("shows the monthly figure as the card's headline and the other figures as labelled facts", () => {
    render(<PathwaysTable comparison={COMPARISON} />);
    const hp = within(screen.getByRole("article", { name: "Hire Purchase" }));

    expect(hp.getByText("RM 4,579.38")).toHaveClass("text-money", "tabular-nums");
    expect(hp.getByText("Upfront cash").nextElementSibling).toHaveTextContent("RM 26,780.00");
    expect(hp.getByText("Total contract outlay").nextElementSibling).toHaveTextContent("RM 301,542.80");
  });

  it("keeps an unavailable pathway as the same card shape with its reason visible", () => {
    render(<PathwaysTable comparison={COMPARISON} />);
    const sub = within(screen.getByRole("article", { name: "Subscription" }));

    expect(sub.getByText("Not available")).toBeInTheDocument();
    expect(sub.getByText("Subscription plans run for 12, 24 or 36 months.")).toBeInTheDocument();
  });
});

describe("Table notes", () => {
  it("does not stop a numeric cell's notes from wrapping (no-wrap is the figure's own choice)", () => {
    render(
      <Table>
        <Table.Body>
          <Table.Row>
            <Table.Cell numeric>a long explanation that is allowed to wrap inside a numeric cell</Table.Cell>
          </Table.Row>
        </Table.Body>
      </Table>,
    );

    expect(screen.getByRole("cell")).not.toHaveClass("whitespace-nowrap");
  });
});
