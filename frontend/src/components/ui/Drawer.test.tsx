import { useState } from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Drawer } from "./Drawer";

// Redesign UI-6b: the side panel (the Audit Log's row details).

function Harness() {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setIsOpen(true)}>
        Open entry
      </button>
      <Drawer isOpen={isOpen} title="Audit entry" subtitle="12 Oct 2026" onClose={() => setIsOpen(false)}>
        <a href="#raw">Raw data</a>
      </Drawer>
    </>
  );
}

describe("Drawer", () => {
  it("is a named modal dialog that takes focus, and Escape closes it back to its opener", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open entry" });

    await user.click(opener);
    const dialog = screen.getByRole("dialog", { name: "Audit entry" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("12 Oct 2026")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("keeps Tab inside the panel", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Open entry" }));

    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("link", { name: "Raw data" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole("link", { name: "Raw data" })).toHaveFocus();
  });

  it("closes from its Close button and from the backdrop", async () => {
    const user = userEvent.setup();
    const { baseElement } = render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Open entry" }));
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open entry" }));
    await user.click(baseElement.querySelector('[aria-hidden="true"].absolute.inset-0') as HTMLElement);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
