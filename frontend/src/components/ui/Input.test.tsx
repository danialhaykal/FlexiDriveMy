import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Input } from "./Input";

describe("Input", () => {
  it("renders a labeled input", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Input label="Downpayment (RM)" value="" onChange={onChange} />);

    const input = screen.getByLabelText("Downpayment (RM)");
    expect(input).toBeInTheDocument();
    expect(input).not.toHaveAttribute("aria-invalid");

    await user.type(input, "1");
    expect(onChange).toHaveBeenCalled();
  });

  it("applies the error state's classes and wires aria attributes", () => {
    render(
      <Input
        label="Downpayment (RM)"
        value="500000"
        onChange={() => {}}
        error="Downpayment cannot exceed the vehicle price"
      />,
    );

    const input = screen.getByLabelText("Downpayment (RM)");
    const errorMessage = screen.getByText("Downpayment cannot exceed the vehicle price");
    expect(input.className).toContain("border-danger-600");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-describedby", errorMessage.id);
  });
});
