import { describe, it, expect } from "vitest";
import {
  equivalenceKey,
  deriveIdempotencyKey,
} from "../commands/command-equivalence";

describe("command-equivalence", () => {
  it("normalizes significant parameters and ignores UX-only fields", () => {
    const a = equivalenceKey("position.modifyProtection", "pos-1", {
      stopLoss: 1.234,
      takeProfit: 1.5,
      note: "ignored",
    });
    const b = equivalenceKey("position.modifyProtection", "pos-1", {
      takeProfit: 1.5,
      stopLoss: 1.234,
      uiToken: "different",
    });
    expect(a).toBe(b);
  });

  it("differs when target changes", () => {
    expect(equivalenceKey("position.close", "pos-1")).not.toBe(
      equivalenceKey("position.close", "pos-2"),
    );
  });

  it("differs when significant param value changes", () => {
    const a = equivalenceKey("position.closePartial", "pos-1", { volume: 0.1 });
    const b = equivalenceKey("position.closePartial", "pos-1", { volume: 0.2 });
    expect(a).not.toBe(b);
  });

  it("idempotency key equals equivalence key", () => {
    expect(deriveIdempotencyKey("order.cancel", "ord-1")).toBe(
      equivalenceKey("order.cancel", "ord-1"),
    );
  });
});
