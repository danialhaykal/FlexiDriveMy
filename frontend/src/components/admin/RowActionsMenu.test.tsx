import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RowActionsMenu } from "./RowActionsMenu";

// Redesign UI-6a: a row's actions behind one icon button, keyboard operable,
// each item running the same handler the old row button ran.

function setup() {
  const onEdit = vi.fn();
  const onArchive = vi.fn();
  render(
    <>
      <RowActionsMenu
        label="Actions for Toyota Camry 2.5V"
        actions={[
          { label: "Edit", onSelect: onEdit },
          { label: "Archive", onSelect: onArchive, tone: "danger" },
        ]}
      />
      <button type="button">Elsewhere</button>
    </>,
  );
  return { onEdit, onArchive, user: userEvent.setup() };
}

describe("RowActionsMenu", () => {
  it("opens a named menu from its icon button and runs the chosen item's handler", async () => {
    const { onEdit, onArchive, user } = setup();
    const trigger = screen.getByRole("button", { name: "Actions for Toyota Camry 2.5V" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu", { name: "Actions for Toyota Camry 2.5V" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Archive" })).toHaveClass("text-danger-700");
    await user.click(screen.getByRole("menuitem", { name: "Archive" }));

    expect(onArchive).toHaveBeenCalledTimes(1);
    expect(onEdit).not.toHaveBeenCalled();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("works from the keyboard: Enter opens on the first item, arrows move, Enter chooses", async () => {
    const { onArchive, user } = setup();
    screen.getByRole("button", { name: "Actions for Toyota Camry 2.5V" }).focus();

    await user.keyboard("{Enter}");
    expect(screen.getByRole("menuitem", { name: "Edit" })).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Archive" })).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Edit" })).toHaveFocus();
    await user.keyboard("{End}");
    expect(screen.getByRole("menuitem", { name: "Archive" })).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(onArchive).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape and returns focus to its button", async () => {
    const { onEdit, user } = setup();
    const trigger = screen.getByRole("button", { name: "Actions for Toyota Camry 2.5V" });
    trigger.focus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Edit" })).toHaveFocus();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("closes on a click outside without running anything", async () => {
    const { onEdit, onArchive, user } = setup();
    await user.click(screen.getByRole("button", { name: "Actions for Toyota Camry 2.5V" }));

    await user.click(screen.getByRole("button", { name: "Elsewhere" }));

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(onEdit).not.toHaveBeenCalled();
    expect(onArchive).not.toHaveBeenCalled();
  });
});
