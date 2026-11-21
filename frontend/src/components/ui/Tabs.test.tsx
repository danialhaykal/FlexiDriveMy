import { useState } from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Tabs } from "./Tabs";

function TestTabs() {
  const [tab, setTab] = useState("one");
  return (
    <Tabs value={tab} onChange={setTab}>
      <Tabs.List aria-label="Test tabs">
        <Tabs.Tab value="one">One</Tabs.Tab>
        <Tabs.Tab value="two">Two</Tabs.Tab>
      </Tabs.List>
      <Tabs.Panel value="one">Panel one content</Tabs.Panel>
      <Tabs.Panel value="two">Panel two content</Tabs.Panel>
    </Tabs>
  );
}

describe("Tabs", () => {
  it("renders only the active panel, with matching ARIA wiring", () => {
    render(<TestTabs />);

    expect(screen.getByRole("tablist", { name: "Test tabs" })).toBeInTheDocument();
    expect(screen.getByText("Panel one content")).toBeInTheDocument();
    expect(screen.queryByText("Panel two content")).not.toBeInTheDocument();

    const tabOne = screen.getByRole("tab", { name: "One" });
    const tabTwo = screen.getByRole("tab", { name: "Two" });
    expect(tabOne).toHaveAttribute("aria-selected", "true");
    expect(tabTwo).toHaveAttribute("aria-selected", "false");

    const panel = screen.getByRole("tabpanel");
    expect(tabOne).toHaveAttribute("aria-controls", panel.id);
    expect(panel).toHaveAttribute("aria-labelledby", tabOne.id);
  });

  it("switches the visible panel when a tab is clicked", async () => {
    const user = userEvent.setup();
    render(<TestTabs />);

    await user.click(screen.getByRole("tab", { name: "Two" }));

    expect(screen.queryByText("Panel one content")).not.toBeInTheDocument();
    expect(screen.getByText("Panel two content")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Two" })).toHaveAttribute("aria-selected", "true");
  });

  it("moves focus to the next tab on ArrowRight and activates it", async () => {
    const user = userEvent.setup();
    render(<TestTabs />);

    screen.getByRole("tab", { name: "One" }).focus();
    await user.keyboard("{ArrowRight}");

    expect(screen.getByRole("tab", { name: "Two" })).toHaveFocus();
    expect(screen.getByText("Panel two content")).toBeInTheDocument();
  });

  // QA audit M9: jsdom doesn't compute real layout (no actual viewport
  // width, no scrollWidth/clientWidth), so a literal "does this overflow
  // at 375px" assertion isn't meaningful in this stack - this instead
  // confirms the CSS that MAKES it scroll (rather than force the page
  // wider) is actually present: a manual check at a real 375px viewport
  // in a browser is the complementary verification for the rendered
  // result (confirmed before shipping - see the Batch 5 report).
  it("makes the tablist horizontally scrollable instead of letting tabs force the page wider", () => {
    render(<TestTabs />);

    const tablist = screen.getByRole("tablist", { name: "Test tabs" });
    expect(tablist.className).toContain("overflow-x-auto");
    expect(tablist.className).toContain("flex-nowrap");
    expect(screen.getByRole("tab", { name: "One" }).className).toContain("shrink-0");
  });

  it("can be a vertical list: Up / Down / Home / End move and activate", async () => {
    function Vertical() {
      const [value, setValue] = useState("a");
      return (
        <Tabs value={value} onChange={setValue}>
          <Tabs.List aria-label="Sections" orientation="vertical">
            <Tabs.Tab value="a">First</Tabs.Tab>
            <Tabs.Tab value="b">Second</Tabs.Tab>
            <Tabs.Tab value="c">Third</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="a">A</Tabs.Panel>
          <Tabs.Panel value="b">B</Tabs.Panel>
          <Tabs.Panel value="c">C</Tabs.Panel>
        </Tabs>
      );
    }
    const user = userEvent.setup();
    render(<Vertical />);

    expect(screen.getByRole("tablist", { name: "Sections" })).toHaveAttribute("aria-orientation", "vertical");
    screen.getByRole("tab", { name: "First" }).focus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("tab", { name: "Second" })).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "Third" })).toHaveFocus();
    expect(screen.getByRole("tabpanel")).toHaveTextContent("C");
    await user.keyboard("{Home}");
    expect(screen.getByRole("tab", { name: "First" })).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("tab", { name: "Third" })).toHaveAttribute("aria-selected", "true");
  });
});

describe("Tabs mobile select (redesign UI-6c)", () => {
  function WithSelect() {
    const [value, setValue] = useState("financing");
    return (
      <Tabs value={value} onChange={setValue}>
        <Tabs.List aria-label="Comparison views" mobileSelectLabel="View">
          <Tabs.Tab value="financing">
            <svg aria-hidden="true" />
            Financing options
          </Tabs.Tab>
          <Tabs.Tab value="tco">Total cost</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="financing">Financing panel</Tabs.Panel>
        <Tabs.Panel value="tco">Total cost panel</Tabs.Panel>
      </Tabs>
    );
  }

  it("offers the same views in a labelled select, which drives the same state as the tabs", async () => {
    const user = userEvent.setup();
    render(<WithSelect />);

    const select = screen.getByLabelText("View") as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => [o.value, o.textContent])).toEqual([
      ["financing", "Financing options"],
      ["tco", "Total cost"],
    ]);
    await user.selectOptions(select, "tco");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Total cost panel");
    expect(screen.getByRole("tab", { name: "Total cost" })).toHaveAttribute("aria-selected", "true");

    await user.click(screen.getByRole("tab", { name: "Financing options" }));
    expect(select).toHaveValue("financing");
  });

  it("shows the select below sm and the strip from sm (class checks)", () => {
    render(<WithSelect />);

    expect(screen.getByLabelText("View").closest(".sm\\:hidden")).not.toBeNull();
    const strip = screen.getByRole("tablist", { name: "Comparison views" });
    expect(strip).toHaveClass("hidden", "sm:flex");
    expect(strip).not.toHaveClass("flex");
  });

  it("adds no select to a list without the option", () => {
    render(
      <Tabs value="a" onChange={() => {}}>
        <Tabs.List aria-label="Plain">
          <Tabs.Tab value="a">A</Tabs.Tab>
        </Tabs.List>
      </Tabs>,
    );

    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByRole("tablist", { name: "Plain" })).toHaveClass("flex");
  });
});
