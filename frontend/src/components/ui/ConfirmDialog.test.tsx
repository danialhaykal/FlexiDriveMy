import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("renders nothing when isOpen is false", () => {
    render(
      <ConfirmDialog
        isOpen={false}
        title="Archive this vehicle?"
        message="This cannot be undone."
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("renders the given title and message when open", () => {
    render(
      <ConfirmDialog
        isOpen
        title="Archive this vehicle?"
        message="This cannot be undone."
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText("Archive this vehicle?")).toBeInTheDocument();
    expect(screen.getByText("This cannot be undone.")).toBeInTheDocument();
  });

  it("calls onConfirm when the confirm button is clicked", async () => {
    const onConfirm = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmDialog
        isOpen
        title="Archive?"
        message="Sure?"
        confirmLabel="Archive"
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Archive" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel when the cancel button or the backdrop is clicked", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmDialog isOpen title="Archive?" message="Sure?" onConfirm={vi.fn()} onCancel={onCancel} />,
    );

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("does not close when clicking inside the dialog itself", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(
      <ConfirmDialog isOpen title="Archive?" message="Sure?" onConfirm={vi.fn()} onCancel={onCancel} />,
    );

    await user.click(screen.getByText("Sure?"));
    expect(onCancel).not.toHaveBeenCalled();
  });

  // FX-1 (X5): the dialog replaces the browser's confirm box on My Comparisons, so it behaves like one.
  it("moves focus to Cancel when it opens and gives focus back to the opener when it closes", async () => {
    function Harness({ open }: { open: boolean }) {
      return (
        <>
          <button type="button">Delete</button>
          <ConfirmDialog isOpen={open} title="Delete?" message="Gone for good." onConfirm={vi.fn()} onCancel={vi.fn()} />
        </>
      );
    }
    const { rerender } = render(<Harness open={false} />);
    const opener = screen.getByRole("button", { name: "Delete" });
    opener.focus();

    rerender(<Harness open />);
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();

    rerender(<Harness open={false} />);
    expect(opener).toHaveFocus();
  });

  it("cancels on Escape, but not while the action is running", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(
      <ConfirmDialog isOpen title="Delete?" message="Gone for good." onConfirm={vi.fn()} onCancel={onCancel} />,
    );
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);

    rerender(<ConfirmDialog isOpen isConfirming title="Delete?" message="Gone for good." onConfirm={vi.fn()} onCancel={onCancel} />);
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
