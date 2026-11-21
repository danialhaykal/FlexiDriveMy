import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Button } from "./Button";

describe("Button", () => {
  it("renders children and defaults to the primary variant", () => {
    render(<Button>Compare pathways</Button>);

    const button = screen.getByRole("button", { name: "Compare pathways" });
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute("data-variant", "primary");
    expect(button.className).toContain("bg-primary-600");
  });

  it.each<[import("./Button").ButtonVariant, string]>([
    ["secondary", "bg-surface"],
    ["ghost", "bg-transparent"],
    ["danger", "bg-danger-600"],
    ["danger-quiet", "text-danger-700"],
  ])("applies the %s variant's classes", (variant, expectedClass) => {
    render(<Button variant={variant}>Action</Button>);

    const button = screen.getByRole("button", { name: "Action" });
    expect(button).toHaveAttribute("data-variant", variant);
    expect(button.className).toContain(expectedClass);
  });

  it("disables the button and shows a busy state while loading", () => {
    render(<Button isLoading>Submitting</Button>);

    const button = screen.getByRole("button", { name: "Submitting" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });

  it("fires onClick when enabled", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Click me</Button>);

    await user.click(screen.getByRole("button", { name: "Click me" }));

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
