import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Table } from "./Table";

function renderComparisonTable() {
  return render(
    <Table>
      <Table.Head>
        <Table.Row>
          <Table.HeaderCell>Pathway</Table.HeaderCell>
          <Table.HeaderCell numeric>Monthly (RM)</Table.HeaderCell>
        </Table.Row>
      </Table.Head>
      <Table.Body>
        <Table.Row>
          <Table.Cell>Hire Purchase</Table.Cell>
          <Table.Cell numeric>5,344.44</Table.Cell>
        </Table.Row>
      </Table.Body>
    </Table>,
  );
}

describe("Table", () => {
  it("renders a real <table> with the given rows and columns", () => {
    renderComparisonTable();

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("Hire Purchase")).toBeInTheDocument();
    expect(screen.getByText("5,344.44")).toBeInTheDocument();
  });

  it("applies tabular-nums and right-alignment only to numeric cells", () => {
    renderComparisonTable();

    const label = screen.getByText("Hire Purchase");
    const figure = screen.getByText("5,344.44");
    const numericHeader = screen.getByText("Monthly (RM)");
    const textHeader = screen.getByText("Pathway");

    expect(figure.className).toContain("tabular-nums");
    expect(figure.className).toContain("text-right");
    expect(label.className).not.toContain("tabular-nums");

    expect(numericHeader.className).toContain("tabular-nums");
    expect(textHeader.className).not.toContain("tabular-nums");
  });

  it("keeps a visually hidden header label inside its own scroll box (redesign UI-6a)", () => {
    const { container } = render(
      <Table>
        <Table.Head>
          <Table.Row>
            <Table.HeaderCell>
              <span className="sr-only">Actions</span>
            </Table.HeaderCell>
          </Table.Row>
        </Table.Head>
      </Table>,
    );

    // An absolutely positioned sr-only label is placed inside a positioned scroll box,
    // so a table wider than the window never widens the page.
    expect(container.firstElementChild).toHaveClass("relative", "overflow-x-auto");
  });
});
