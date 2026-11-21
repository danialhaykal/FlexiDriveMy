import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { EmptyState } from "./EmptyState";
import { Button } from "./Button";

describe("EmptyState", () => {
  it("renders the title only when that's all that's given", () => {
    render(<EmptyState title="No vehicles match your filters" />);

    expect(screen.getByText("No vehicles match your filters")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders the description and action when provided", () => {
    render(
      <EmptyState
        title="No vehicles match your filters"
        description="Try broadening your filter parameters."
        action={<Button>Reset all filters</Button>}
      />,
    );

    expect(screen.getByText("Try broadening your filter parameters.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset all filters" })).toBeInTheDocument();
  });

  it("shows an optional icon above the title, hidden from screen readers", () => {
    const { container } = render(<EmptyState icon={<svg data-testid="icon" />} title="Select vehicles to compare" />);

    const wrapper = screen.getByTestId("icon").parentElement as HTMLElement;
    expect(wrapper).toHaveAttribute("aria-hidden", "true");
    expect(wrapper.nextElementSibling).toHaveTextContent("Select vehicles to compare");
    expect(container.querySelectorAll("[aria-hidden='true']")).toHaveLength(1);
  });

  it("has no icon unless one is given", () => {
    const { container } = render(<EmptyState title="Nothing here" />);

    expect(container.querySelector("[aria-hidden='true']")).toBeNull();
  });
});
