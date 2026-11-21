import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { saveScenario } from "../../api/scenarios";
import { parseApiErrorMessage } from "../../lib/apiErrors";
import type { ComparisonResult, MileageBand } from "../../types/comparisons";
import type { ScenarioInputs, ScoringRequestInputs } from "../../types/scenarios";
import { Button } from "../ui/Button";
import { Input } from "../ui/Input";

// F009 / UC009 "Save this Comparison". Sends the INPUTS on screen - never
// a figure: the server recalculates the comparison, the total cost and the
// AI Recommendation with the same services as the live screens and stores
// that snapshot (run 1 fix batch 2). The comparison prop only gates the
// button; none of its values is sent.
//
// FX-1 (X3, X5): the total cost is always asked for (a saved comparison has
// its Total cost section even if that tab was never opened; the server stores
// its reason when it can't build one), and the recommendation request is the
// CURRENT shared ratings / income / Max DSR - not the last request the AI tab
// happened to send, which went stale when the Max DSR changed on another tab.

interface SaveScenarioButtonProps {
  vehicleId: number;
  comparison: ComparisonResult | null;
  // The recommendation request for the current ratings, income and Max DSR
  // (null while any of them is missing).
  scoringRequest: ScoringRequestInputs | null;
  tenureMonths: number;
  mileageBand: MileageBand;
  downpayment: string;
}

const GENERIC_ERROR = "Could not save this comparison. Please try again.";

export function SaveScenarioButton({
  vehicleId,
  comparison,
  scoringRequest,
  tenureMonths,
  mileageBand,
  downpayment,
}: SaveScenarioButtonProps) {
  const [mode, setMode] = useState<"idle" | "editing">("idle");
  const [title, setTitle] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isDuplicate, setIsDuplicate] = useState(false);
  // FX-2 (item 3): "Comparison saved." with a link to My Comparisons, announced
  // as a status. It stays until the form is opened again (it used to vanish
  // after 4 s, which a link must not do).
  const [isSaved, setIsSaved] = useState(false);
  // FX-2 (item 2): closing the form (Save, Cancel or Escape) gives focus back
  // to the "Save this Comparison" button that opened it.
  const idleRef = useRef<HTMLDivElement>(null);
  const [returnFocus, setReturnFocus] = useState(false);

  useEffect(() => {
    if (mode !== "idle" || !returnFocus) return;
    idleRef.current?.querySelector("button")?.focus();
    setReturnFocus(false);
  }, [mode, returnFocus]);

  async function submit(overwrite: boolean) {
    if (!comparison) return;
    setIsSaving(true);
    setError(null);
    const inputs: ScenarioInputs = {
      tenure_months: tenureMonths,
      mileage_band: mileageBand,
      downpayment,
      include_tco: true,
      scoring: scoringRequest,
    };
    try {
      await saveScenario({ title: title.trim(), vehicle: vehicleId, inputs, overwrite });
      setIsSaved(true);
      setReturnFocus(true);
      setMode("idle");
      setTitle("");
      setIsDuplicate(false);
    } catch (err: unknown) {
      if (axios.isAxiosError(err) && err.response?.status === 409) {
        const detail = (err.response.data as { detail?: unknown } | undefined)?.detail;
        setError(typeof detail === "string" ? detail : GENERIC_ERROR);
        setIsDuplicate(true);
      } else if (axios.isAxiosError(err) && err.response?.status === 400) {
        // QA audit M13: e.g. a scenario title over the server's max
        // length - previously fell straight through to GENERIC_ERROR,
        // even though DRF already returned the real reason.
        setError(parseApiErrorMessage(err.response.data) ?? GENERIC_ERROR);
        setIsDuplicate(false);
      } else {
        setError(GENERIC_ERROR);
        setIsDuplicate(false);
      }
    } finally {
      setIsSaving(false);
    }
  }

  function handleCancel() {
    setReturnFocus(true);
    setMode("idle");
    setTitle("");
    setError(null);
    setIsDuplicate(false);
  }

  if (mode === "idle") {
    return (
      <div ref={idleRef} className="flex flex-col items-start gap-2">
        <Button
          variant="secondary"
          onClick={() => {
            setIsSaved(false);
            setMode("editing");
          }}
          disabled={!comparison}
        >
          Save this Comparison
        </Button>
        <p role="status" className="text-small text-positive-700">
          {isSaved && (
            <>
              Comparison saved.{" "}
              <Link to="/scenarios" className="font-semibold underline">
                Open in My Comparisons
              </Link>
            </>
          )}
        </p>
      </div>
    );
  }

  return (
    <form
      className="flex flex-col items-start gap-3 rounded-md border border-border bg-surface p-3"
      onKeyDown={(event) => {
        // FX-2 (item 2): Escape closes the form like Cancel (not while saving).
        if (event.key === "Escape" && !isSaving) {
          event.preventDefault();
          handleCancel();
        }
      }}
      onSubmit={(event) => {
        // QA audit L3: pressing Enter in the title field previously did
        // nothing (a bare <input>, not inside a <form>, never auto-
        // submits on Enter) - wrapping in a real <form> with a
        // type="submit" button makes Enter behave the same as clicking
        // Save, the platform-native expectation for a single-line text
        // field.
        event.preventDefault();
        if (title.trim() !== "") void submit(false);
      }}
    >
      <Input
        label="Comparison title"
        value={title}
        onChange={(event) => {
          setTitle(event.target.value);
          setError(null);
          setIsDuplicate(false);
        }}
        // Cosmetic: Honda isn't in the locked catalog (the project spec:
        // BMW/Mercedes-Benz/Lexus/Porsche/Toyota only) - an in-scope
        // example avoids suggesting a brand this platform doesn't cover.
        placeholder="e.g. BMW 3 Series - 36mo GFV"
        autoFocus
      />
      <div className="flex flex-wrap gap-2">
        <Button type="submit" isLoading={isSaving} disabled={title.trim() === ""}>
          Save
        </Button>
        {isDuplicate && (
          <Button
            type="button"
            variant="secondary"
            onClick={() => void submit(true)}
            isLoading={isSaving}
          >
            Overwrite existing
          </Button>
        )}
        <Button type="button" variant="ghost" onClick={handleCancel} disabled={isSaving}>
          Cancel
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-small text-danger-700">
          {error}
        </p>
      )}
    </form>
  );
}
