import { describe, expect, it } from "vitest";
import { parseApiErrorMessage, parseApiFieldErrors } from "./apiErrors";

describe("parseApiErrorMessage", () => {
  it("returns the first field-level message, for ANY field name, not a hardcoded allowlist", () => {
    expect(parseApiErrorMessage({ monthly_income: ["Must be a positive amount."] })).toBe(
      "Must be a positive amount.",
    );
    expect(parseApiErrorMessage({ max_dsr_percent: ["Must be between 0 and 100."] })).toBe(
      "Must be between 0 and 100.",
    );
    expect(parseApiErrorMessage({ title: ["Ensure this field has no more than 100 characters."] })).toBe(
      "Ensure this field has no more than 100 characters.",
    );
  });

  it("falls back to detail when there is no field-level error", () => {
    expect(parseApiErrorMessage({ detail: "No active interest rate configured." })).toBe(
      "No active interest rate configured.",
    );
  });

  it("prefers a field-level message over detail when both are present", () => {
    expect(
      parseApiErrorMessage({
        downpayment: ["Ensure that there are no more than 2 decimal places."],
        detail: "Validation failed.",
      }),
    ).toBe("Ensure that there are no more than 2 decimal places.");
  });

  it("returns null (caller falls back to its own generic message) for an unusable body", () => {
    expect(parseApiErrorMessage(null)).toBeNull();
    expect(parseApiErrorMessage(undefined)).toBeNull();
    expect(parseApiErrorMessage("plain text, not JSON")).toBeNull();
    expect(parseApiErrorMessage({})).toBeNull();
    expect(parseApiErrorMessage({ some_field: [] })).toBeNull();
    expect(parseApiErrorMessage({ some_field: 42 })).toBeNull();
  });

  it("handles a bare string field value (not every DRF error is a list)", () => {
    expect(parseApiErrorMessage({ non_field_errors: "Something went wrong." })).toBe(
      "Something went wrong.",
    );
  });
});

describe("parseApiFieldErrors", () => {
  it("returns every field's first message, not just one", () => {
    expect(
      parseApiFieldErrors({
        brand: ["'Toyota' already has an active interest rate. Archive it first, then create the replacement."],
        rate_percent: ["Interest rate input exceeds acceptable limits (0.01% – 15.00%)."],
      }),
    ).toEqual({
      brand: "'Toyota' already has an active interest rate. Archive it first, then create the replacement.",
      rate_percent: "Interest rate input exceeds acceptable limits (0.01% – 15.00%).",
    });
  });

  it("excludes detail, since that's a non-field-level message", () => {
    expect(parseApiFieldErrors({ detail: "No active interest rate configured." })).toEqual({});
  });

  it("returns an empty object for an unusable body", () => {
    expect(parseApiFieldErrors(null)).toEqual({});
    expect(parseApiFieldErrors("plain text")).toEqual({});
    expect(parseApiFieldErrors({})).toEqual({});
  });
});
