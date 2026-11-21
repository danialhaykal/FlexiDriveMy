import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { SaveScenarioButton } from "./SaveScenarioButton";
import { saveScenario } from "../../api/scenarios";
import type { ComparisonResult } from "../../types/comparisons";
import type { ScoringRequestInputs } from "../../types/scenarios";

vi.mock("../../api/scenarios", () => ({
  saveScenario: vi.fn(),
}));

const mockedSaveScenario = vi.mocked(saveScenario);

function makeComparison(): ComparisonResult {
  return {
    vehicle_id: 1,
    tenure_months: 36,
    mileage_band: "standard",
    downpayment: "40000.00",
    hire_purchase: {
      monthly_instalment: "10900.00",
      upfront_cash: "40000.00",
      total_contract_outlay: "432400.00",
    },
    gfv_leasing: null,
    subscription: null,
    unavailable: {},
  } as unknown as ComparisonResult;
}

function renderButton() {
  return render(
    <MemoryRouter>
      <SaveScenarioButton
        vehicleId={1}
        comparison={makeComparison()}
        scoringRequest={null}
        tenureMonths={36}
        mileageBand="standard"
        downpayment="40000.00"
      />
    </MemoryRouter>,
  );
}

describe("SaveScenarioButton", () => {
  // --- QA audit L3 ---------------------------------------------------------

  it("saves when Enter is pressed in the title field, not just on a Save click", async () => {
    mockedSaveScenario.mockResolvedValueOnce({ id: 1 } as never);
    const user = userEvent.setup();
    renderButton();

    await user.click(
      screen.getByRole("button", { name: "Save this Comparison" }),
    );
    await user.type(
      screen.getByLabelText("Comparison title"),
      "My scenario{Enter}",
    );

    expect(mockedSaveScenario).toHaveBeenCalledWith(
      expect.objectContaining({ title: "My scenario" }),
    );
    expect(
      await screen.findByText(
        /^Comparison saved\./,
      ) /* FX-2 item 3: was "Comparison saved to your portfolio." */,
    ).toBeInTheDocument();
  });

  // --- Run 1 fix batch 2 (G6): inputs only, never figures ------------------------
  // (The Islamic-financing wording is now read from the user's profile by
  // the server, as the PDF export does - nothing here sends it.)

  const SCORING_REQUEST: ScoringRequestInputs = {
    upfront_cash_preservation: 4,
    maintenance_protection: 3,
    ownership_equity: 2,
    monthly_income: "8000",
    max_dsr_percent: "40",
  };

  async function saveWith(props: {
    scoringRequest: ScoringRequestInputs | null;
  }) {
    mockedSaveScenario.mockResolvedValueOnce({ id: 1 } as never);
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <SaveScenarioButton
          vehicleId={1}
          comparison={makeComparison()}
          tenureMonths={36}
          mileageBand="standard"
          downpayment="40000.00"
          {...props}
        />
      </MemoryRouter>,
    );
    await user.click(
      screen.getByRole("button", { name: "Save this Comparison" }),
    );
    await user.type(screen.getByLabelText("Comparison title"), "Snap{Enter}");
    await screen.findByText(/^Comparison saved\./); // FX-2 item 3: was "Comparison saved to your portfolio."
    return mockedSaveScenario.mock.calls[
      mockedSaveScenario.mock.calls.length - 1
    ][0];
  }

  // FX-1 (X5): the total cost is always asked for (include_tco was false until the Total cost tab had a result).
  it("sends the inputs and no figures, always asking for the total cost, with no scoring request while unrated", async () => {
    const sent = await saveWith({ scoringRequest: null });

    expect(sent).toEqual({
      title: "Snap",
      vehicle: 1,
      inputs: {
        tenure_months: 36,
        mileage_band: "standard",
        downpayment: "40000.00",
        include_tco: true,
        scoring: null,
      },
      overwrite: false,
    });
  });

  it("asks for the TCO and sends the scoring request it is given", async () => {
    const sent = await saveWith({ scoringRequest: SCORING_REQUEST });

    expect(sent.inputs).toEqual({
      tenure_months: 36,
      mileage_band: "standard",
      downpayment: "40000.00",
      include_tco: true,
      scoring: SCORING_REQUEST,
    });
    expect(JSON.stringify(sent)).not.toMatch(
      /monthly_instalment|tco_net|suitability_score/,
    );
  });

  // FX-1 (X3): the request is the current ratings / income / Max DSR, whether or not the AI tab has a result for them
  // (it was dropped here while that tab had no result; the server builds the recommendation from the request).
  it("sends the current scoring request even when the recommendation tab has no result for it", async () => {
    const sent = await saveWith({ scoringRequest: SCORING_REQUEST });

    expect(sent.inputs.scoring).toEqual(SCORING_REQUEST);
    expect(sent.inputs.include_tco).toBe(true);
  });

  it("shows a nested inputs error from the server, not the generic fallback", async () => {
    mockedSaveScenario.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 400,
        data: {
          inputs: {
            downpayment: [
              "Minimum downpayment is 10% of the vehicle price (RM 4,000.00).",
            ],
          },
        },
      },
    });
    const user = userEvent.setup();
    renderButton();

    await user.click(
      screen.getByRole("button", { name: "Save this Comparison" }),
    );
    await user.type(screen.getByLabelText("Comparison title"), "Nested{Enter}");

    expect(
      await screen.findByText(
        "Minimum downpayment is 10% of the vehicle price (RM 4,000.00).",
      ),
    ).toBeInTheDocument();
  });

  // --- QA audit M13 -------------------------------------------------------

  it("surfaces a DRF field error for an over-length title, not the generic fallback", async () => {
    mockedSaveScenario.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 400,
        data: { title: ["Ensure this field has no more than 100 characters."] },
      },
    });

    const user = userEvent.setup();
    renderButton();

    await user.click(
      screen.getByRole("button", { name: "Save this Comparison" }),
    );
    await user.type(screen.getByLabelText("Comparison title"), "a".repeat(120));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText(
        "Ensure this field has no more than 100 characters.",
      ),
    ).toBeInTheDocument();
  });
});

describe("SaveScenarioButton (FX-2)", () => {
  beforeEach(() => {
    mockedSaveScenario.mockReset();
  });

  // item 2
  it("Escape closes the form and gives focus back to 'Save this Comparison'", async () => {
    const user = userEvent.setup();
    renderButton();

    await user.click(screen.getByRole("button", { name: "Save this Comparison" }));
    await user.type(screen.getByLabelText("Comparison title"), "Draft");
    await user.keyboard("{Escape}");

    expect(screen.queryByLabelText("Comparison title")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save this Comparison" })).toHaveFocus();
    expect(mockedSaveScenario).not.toHaveBeenCalled();
  });

  // item 3
  it("after saving, closes the form and announces 'Comparison saved.' with a link to My Comparisons", async () => {
    mockedSaveScenario.mockResolvedValueOnce({ id: 9 } as never);
    const user = userEvent.setup();
    renderButton();

    await user.click(screen.getByRole("button", { name: "Save this Comparison" }));
    await user.type(screen.getByLabelText("Comparison title"), "Keep{Enter}");

    const status = await screen.findByRole("status");
    await vi.waitFor(() => expect(status).toHaveTextContent("Comparison saved. Open in My Comparisons"));
    expect(screen.getByRole("link", { name: "Open in My Comparisons" })).toHaveAttribute("href", "/scenarios");
    expect(screen.queryByLabelText("Comparison title")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save this Comparison" })).toHaveFocus();
  });

  it("keeps the duplicate-title flow: the server's message and Overwrite existing", async () => {
    mockedSaveScenario.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 409, data: { detail: "A comparison with this title already exists. Please choose a different title or overwrite the existing comparison." } },
    });
    const user = userEvent.setup();
    renderButton();

    await user.click(screen.getByRole("button", { name: "Save this Comparison" }));
    await user.type(screen.getByLabelText("Comparison title"), "Dup{Enter}");

    expect(await screen.findByText(/A comparison with this title already exists/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Overwrite existing" })).toBeInTheDocument();
  });
});
