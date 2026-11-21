import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Select } from "./Select";

const OPTIONS = [
  { value: "low", label: "Low (< 10k km/yr)" },
  { value: "standard", label: "Standard (10-15k km/yr)" },
];

describe("Select", () => {
  it("renders a labeled select with its options", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Select label="Mileage band" value="low" onChange={onChange} options={OPTIONS} />);

    const select = screen.getByLabelText("Mileage band");
    expect(select).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Standard (10-15k km/yr)" })).toBeInTheDocument();

    await user.selectOptions(select, "standard");
    expect(onChange).toHaveBeenCalled();
  });

  it("applies the error state's classes and wires aria attributes", () => {
    render(
      <Select
        label="Mileage band"
        value="low"
        onChange={() => {}}
        options={OPTIONS}
        error="Required"
      />,
    );

    const select = screen.getByLabelText("Mileage band");
    const errorMessage = screen.getByText("Required");
    expect(select.className).toContain("border-danger-600");
    expect(select).toHaveAttribute("aria-invalid", "true");
    expect(select).toHaveAttribute("aria-describedby", errorMessage.id);
  });

  it("folds the help text into an expander when given a summary, still describing the select", () => {
    render(
      <Select
        label="Mileage band"
        value="low"
        onChange={() => {}}
        options={OPTIONS}
        helpText="Check your last renewal notice."
        helpSummary="Where do I find this?"
      />,
    );

    const select = screen.getByLabelText("Mileage band");
    const help = screen.getByText("Check your last renewal notice.");
    expect(help.closest("details")?.querySelector("summary")).toHaveTextContent("Where do I find this?");
    expect(select).toHaveAttribute("aria-describedby", help.id);
    expect(select).toHaveAccessibleDescription("Check your last renewal notice.");
  });
});
