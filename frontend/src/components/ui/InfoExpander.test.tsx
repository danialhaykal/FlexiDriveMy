import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { InfoExpander } from "./InfoExpander";

describe("InfoExpander", () => {
  it("is folded by default with the default label, and its text is still in the page", () => {
    const { container } = render(<InfoExpander>Rates are flat rates, the way dealers quote them.</InfoExpander>);

    const details = container.querySelector("details");
    expect(details).not.toHaveAttribute("open");
    expect(screen.getByText("How is this calculated?").closest("summary")).not.toBeNull();
    // folded, yet the caveat is in the DOM (find-in-page, screen readers and tests reach it)
    const text = screen.getByText("Rates are flat rates, the way dealers quote them.");
    expect(details).toContainElement(text);
  });

  // Opening with Enter/Space is the browser's own <summary> behaviour (jsdom does not
  // emulate it, so it is checked in a real browser); here the summary is focusable
  // and a click opens it.
  it("takes its own label, can start open, and opens on a click", async () => {
    const user = userEvent.setup();
    const { container, rerender } = render(<InfoExpander summary="What the fee covers">Fee parts</InfoExpander>);
    const details = container.querySelector("details")!;
    const summary = screen.getByText("What the fee covers").closest("summary")!;

    summary.focus();
    expect(summary).toHaveFocus();
    await user.click(summary);
    expect(details).toHaveAttribute("open");

    rerender(<InfoExpander summary="What the fee covers" defaultOpen>Fee parts</InfoExpander>);
    expect(container.querySelector("details")).toHaveAttribute("open");
  });

  it("hides its icon from screen readers", () => {
    const { container } = render(<InfoExpander>Text</InfoExpander>);

    expect(container.querySelector("summary svg")).toHaveAttribute("aria-hidden", "true");
  });
});
