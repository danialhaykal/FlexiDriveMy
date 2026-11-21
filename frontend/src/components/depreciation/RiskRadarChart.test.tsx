import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RiskRadarChart } from "./RiskRadarChart";
import type { RiskRadarPathwayScores } from "../../types/depreciation";

const SCORES: RiskRadarPathwayScores = {
  upfront_cash_preservation: "0.9000",
  maintenance_protection: "0.0000",
  ownership_equity: "1.0000",
};

describe("RiskRadarChart", () => {
  it("plots one Radar series per available pathway, named in the legend", () => {
    render(
      <RiskRadarChart
        radar={{ hire_purchase: SCORES, subscription: { ...SCORES, ownership_equity: "0.0000" } }}
        unavailable={{}}
      />,
    );

    expect(screen.getByText("Hire Purchase")).toBeInTheDocument();
    expect(screen.getByText("Subscription")).toBeInTheDocument();
  });

  it("lists an unavailable pathway as plain text, not an empty/zeroed radar line", () => {
    render(
      <RiskRadarChart
        radar={{ hire_purchase: SCORES }}
        unavailable={{ gfv_leasing: "No active GFV residual ratio configured." }}
      />,
    );

    expect(screen.getByText("GFV Leasing:")).toBeInTheDocument();
    expect(screen.getByText("No active GFV residual ratio configured.")).toBeInTheDocument();
  });

  it("renders nothing in the unavailable list when every pathway is available", () => {
    render(<RiskRadarChart radar={{ hire_purchase: SCORES }} unavailable={{}} />);

    expect(screen.queryByText(/No active/)).not.toBeInTheDocument();
  });

  // Live-walkthrough finding: a scenario saved before Batch 6C added
  // risk_radar/radar_unavailable has neither key at all in its stored
  // payload - both are genuinely `undefined`, not `{}`, and previously
  // threw calling Object.keys() on them.
  it("renders without crashing when radar and unavailable are both undefined", () => {
    expect(() => render(<RiskRadarChart radar={undefined} unavailable={undefined} />)).not.toThrow();
  });

  // Run 3 fix batch 5 (F-28): the legend labels are in ink (WCAG AA), not the series colour.
  it("writes the legend labels in the ink colour", () => {
    render(
      <RiskRadarChart
        radar={{ hire_purchase: SCORES, gfv_leasing: SCORES, subscription: { ...SCORES, ownership_equity: "0.0000" } }}
        unavailable={{}}
      />,
    );

    for (const name of ["Hire Purchase", "GFV Leasing", "Subscription"]) {
      expect(screen.getByText(name)).toHaveStyle({ color: "var(--color-ink)" });
    }
  });
});
