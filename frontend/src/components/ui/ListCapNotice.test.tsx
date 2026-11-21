import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ListCapNotice } from "./ListCapNotice";

// Run 3 fix batch 4 (F-17): the "Showing N of M" line appears only when the
// all-pages safety cap cut a list short.

describe("ListCapNotice", () => {
  it("says how many rows are shown out of the server's total when the list was cut short", () => {
    render(<ListCapNotice shown={2500} total={2612} />);
    expect(screen.getByRole("status")).toHaveTextContent("Showing 2,500 of 2,612 rows.");
  });

  it("renders nothing when every row is shown", () => {
    const { container } = render(<ListCapNotice shown={93} total={93} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for an empty list", () => {
    const { container } = render(<ListCapNotice shown={0} total={0} />);
    expect(container).toBeEmptyDOMElement();
  });
});
