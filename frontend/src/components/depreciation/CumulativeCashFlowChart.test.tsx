import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { CumulativeCashFlowChart } from "./CumulativeCashFlowChart";
import type { CumulativeCashFlowPoint } from "../../types/depreciation";

const CASH_FLOW: CumulativeCashFlowPoint[] = [
  { month: 0, cumulative_cash_outflow: "10000.00" },
  { month: 1, cumulative_cash_outflow: "10908.33" },
  { month: 2, cumulative_cash_outflow: "11816.66" },
];

describe("CumulativeCashFlowChart", () => {
  it("renders the area series with the data-export-chart hook ExportPdfButton relies on", () => {
    const { container } = render(<CumulativeCashFlowChart cumulativeCashFlow={CASH_FLOW} />);

    expect(container.querySelector('[data-export-chart="tco-cumulative-cash-flow"]')).not.toBeNull();
    expect(container.querySelector("path.recharts-area-area")).not.toBeNull();
  });

  // Live-walkthrough finding: a scenario saved before Batch 6C added
  // cumulative_cash_flow has no such key at all in its stored payload -
  // `cumulativeCashFlow` is genuinely `undefined`, not `[]`, and
  // previously threw calling `.map()` on it.
  it("renders without crashing when cumulativeCashFlow is undefined", () => {
    expect(() => render(<CumulativeCashFlowChart cumulativeCashFlow={undefined} />)).not.toThrow();
  });
});
