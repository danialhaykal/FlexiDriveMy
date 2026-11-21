import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AdminListToolbar, NoMatchingRows, useAdminListFilter } from "./AdminListToolbar";

// Redesign UI-6a: the admin list toolbar only filters the rows already loaded;
// Active is the default, and each filter shows how many rows it holds.

interface Row {
  id: number;
  name: string;
  is_active: boolean;
}

const ROWS: Row[] = [
  { id: 1, name: "BMW 3 Series", is_active: true },
  { id: 2, name: "Toyota Alphard", is_active: true },
  { id: 3, name: "QA Archived Car", is_active: false },
];

function Harness({ rows = ROWS }: { rows?: Row[] }) {
  const list = useAdminListFilter(rows, (row) => row.is_active, (row) => row.name);
  return (
    <>
      <AdminListToolbar searchLabel="Search cars" {...list.toolbarProps} action={<button type="button">Add</button>} />
      <ul aria-label="Rows">
        {list.visible.map((row) => (
          <li key={row.id}>{row.name}</li>
        ))}
      </ul>
      {list.visible.length === 0 && <NoMatchingRows status={list.status} hasSearch={list.search !== ""} />}
    </>
  );
}

const shown = () => screen.queryAllByRole("listitem").map((item) => item.textContent);

describe("AdminListToolbar", () => {
  it("shows Active by default, with a count for each filter", () => {
    render(<Harness />);

    expect(screen.getByRole("button", { name: "Active (2)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Archived (1)" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "All (3)" })).toHaveAttribute("aria-pressed", "false");
    expect(shown()).toEqual(["BMW 3 Series", "Toyota Alphard"]);
    expect(screen.getByRole("button", { name: "Add" })).toBeInTheDocument();
  });

  it("switches to Archived and All", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "Archived (1)" }));
    expect(shown()).toEqual(["QA Archived Car"]);
    await user.click(screen.getByRole("button", { name: "All (3)" }));
    expect(shown()).toEqual(["BMW 3 Series", "Toyota Alphard", "QA Archived Car"]);
  });

  it("searches the visible text of the rows in the chosen filter, case-insensitively; counts don't move", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.type(screen.getByRole("searchbox", { name: "Search cars" }), "toyota");
    expect(shown()).toEqual(["Toyota Alphard"]);
    expect(screen.getByRole("button", { name: "Active (2)" })).toBeInTheDocument();

    await user.clear(screen.getByRole("searchbox", { name: "Search cars" }));
    await user.type(screen.getByRole("searchbox", { name: "Search cars" }), "archived");
    expect(shown()).toEqual([]);
    expect(screen.getByText("No rows match your search.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "All (3)" }));
    expect(shown()).toEqual(["QA Archived Car"]);
  });

  it("says so when a filter holds no rows", async () => {
    const user = userEvent.setup();
    render(<Harness rows={[ROWS[0]]} />);

    await user.click(screen.getByRole("button", { name: "Archived (0)" }));
    expect(screen.getByText("No archived rows.")).toBeInTheDocument();
  });
});
