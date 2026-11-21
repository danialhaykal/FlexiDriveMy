import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RangeSlider } from "./RangeSlider";

describe("RangeSlider", () => {
  it("renders the label, the slider, and the formatted current value", () => {
    render(
      <RangeSlider
        label="Tenure"
        value={36}
        min={12}
        max={108}
        step={12}
        formatValue={(v) => `${v} months`}
        onChange={() => {}}
      />,
    );

    const slider = screen.getByLabelText("Tenure");
    expect(slider).toBeInTheDocument();
    expect(slider).toHaveAttribute("type", "range");
    expect(slider.className).toContain("accent-primary-600");

    const valueDisplay = screen.getByText("36 months");
    expect(valueDisplay.className).toContain("tabular-nums");
  });

  it("calls onChange with a number when moved", () => {
    const onChange = vi.fn();
    render(
      <RangeSlider label="Tenure" value={36} min={12} max={108} step={12} onChange={onChange} />,
    );

    fireEvent.change(screen.getByLabelText("Tenure"), { target: { value: "60" } });

    expect(onChange).toHaveBeenCalledWith(60);
  });

  it("falls back to a plain string when no formatValue is given", () => {
    render(<RangeSlider label="Downpayment" value={10000} min={0} max={50000} onChange={() => {}} />);

    expect(screen.getByText("10000")).toBeInTheDocument();
  });

  // --- QA audit M5 -----------------------------------------------------

  it("shows a 'Not yet rated' badge when isUnset is true, and not otherwise", () => {
    const { rerender } = render(
      <RangeSlider label="Upfront cash" value={3} min={1} max={5} onChange={() => {}} isUnset />,
    );
    expect(screen.getByText("Not yet rated")).toBeInTheDocument();

    rerender(<RangeSlider label="Upfront cash" value={3} min={1} max={5} onChange={() => {}} />);
    expect(screen.queryByText("Not yet rated")).not.toBeInTheDocument();
  });

  it("commits the current value on pointerup even when it matches the already-displayed value", () => {
    // The literal M5 bug: a native range input fires no change/input
    // event at all if the committed value equals what's already shown -
    // this is the fallback this component needs so "pick the same
    // number the unanswered display happened to show" still registers.
    const onChange = vi.fn();
    render(<RangeSlider label="Upfront cash" value={3} min={1} max={5} onChange={onChange} isUnset />);

    const slider = screen.getByLabelText("Upfront cash") as HTMLInputElement;
    fireEvent.pointerUp(slider);

    expect(onChange).toHaveBeenCalledWith(3);
  });

  it("commits the current value on keyup of a key that moves the slider", () => {
    const onChange = vi.fn();
    render(<RangeSlider label="Upfront cash" value={3} min={1} max={5} onChange={onChange} isUnset />);

    fireEvent.keyUp(screen.getByLabelText("Upfront cash"), { key: "ArrowRight" });

    expect(onChange).toHaveBeenCalledWith(3);
  });

  it("does NOT count Tab (or any non-adjusting key) as answering the slider", () => {
    const onChange = vi.fn();
    render(<RangeSlider label="Upfront cash" value={null} min={1} max={5} onChange={onChange} />);

    fireEvent.keyUp(screen.getByLabelText("Upfront cash"), { key: "Tab" });
    fireEvent.keyUp(screen.getByLabelText("Upfront cash"), { key: "Shift" });

    expect(onChange).not.toHaveBeenCalled();
  });

  // --- Audit batch 6 (F2): an unrated slider never shows a number ------------

  it("shows no number at all while the value is null, only the 'Not yet rated' badge", () => {
    const { container } = render(
      <RangeSlider label="Upfront cash" value={null} min={1} max={5} onChange={() => {}} />,
    );

    expect(screen.getByText("Not yet rated")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\d/);
    expect(screen.getByLabelText("Upfront cash")).toHaveAttribute("aria-valuetext", "Not yet rated");
    expect(screen.getByLabelText("Upfront cash").className).not.toContain("accent-primary-600");
  });

  it("hides the number even when a caller passes one together with isUnset", () => {
    const { container } = render(
      <RangeSlider label="Upfront cash" value={3} min={1} max={5} onChange={() => {}} isUnset />,
    );

    expect(container.textContent).not.toMatch(/\d/);
  });

  // --- Run 1 fix batch 5 (A10): one click or tap on the resting position rates it ----

  it("rates an unrated 1-5 slider 3 with a single click on its starting position", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<RangeSlider label="Upfront cash" value={null} min={1} max={5} onChange={onChange} />);

    await user.click(screen.getByLabelText("Upfront cash"));

    expect(onChange).toHaveBeenCalledWith(3);
  });

  it("rates it on a tap even when the touch browser cancels the pointer-up", () => {
    const onChange = vi.fn();
    render(<RangeSlider label="Upfront cash" value={null} min={1} max={5} onChange={onChange} />);
    const slider = screen.getByLabelText("Upfront cash");

    fireEvent.pointerDown(slider);
    fireEvent.click(slider); // no pointerup reached the input

    expect(onChange).toHaveBeenCalledWith(3);
  });

  it("does NOT rate it when only its label is clicked, or it only gets Tab focus", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<RangeSlider label="Upfront cash" value={null} min={1} max={5} onChange={onChange} />);

    await user.click(screen.getByText("Upfront cash")); // fires a click on the input, no press on it
    await user.tab();
    await user.tab({ shift: true });

    expect(onChange).not.toHaveBeenCalled();
  });

  it("shows the number again, and the normal colour, once the value is real", () => {
    render(<RangeSlider label="Upfront cash" value={4} min={1} max={5} onChange={() => {}} />);

    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.queryByText("Not yet rated")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Upfront cash")).not.toHaveAttribute("aria-valuetext");
  });
});

// FX-2 (item 4): labelled ticks (a native datalist too) and one hint line, described to assistive tech.
describe("RangeSlider marks and hint", () => {
  it("labels the ticks, links them to the slider, and describes the slider with the hint", () => {
    render(
      <RangeSlider
        label="Tenure"
        value={72}
        min={12}
        max={108}
        onChange={() => {}}
        marks={[12, 24, 36, 48, 60]}
        hint="Subscription plans run for 12, 24 or 36 months."
      />,
    );

    const slider = screen.getByRole("slider", { name: "Tenure" });
    const list = document.getElementById(slider.getAttribute("list")!)!;
    expect(Array.from(list.querySelectorAll("option")).map((o) => o.getAttribute("value"))).toEqual([
      "12", "24", "36", "48", "60",
    ]);
    for (const mark of ["12", "24", "36", "48", "60"]) expect(screen.getByText(mark)).toBeInTheDocument();
    expect(slider).toHaveAccessibleDescription("Subscription plans run for 12, 24 or 36 months.");
    expect(slider).toHaveAttribute("step", "1"); // any month is still allowed
  });

  it("shows neither without the props", () => {
    render(<RangeSlider label="Tenure" value={36} min={12} max={108} onChange={() => {}} />);

    expect(screen.getByRole("slider", { name: "Tenure" })).not.toHaveAttribute("list");
    expect(screen.getByRole("slider", { name: "Tenure" })).not.toHaveAttribute("aria-describedby");
  });
});
