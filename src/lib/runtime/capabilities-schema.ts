import { z } from "zod";
import type { RuntimeCapabilities, RuntimeCommandKind } from "./runtime-types";

const commandKinds = [
  "runtime.start",
  "runtime.pause",
  "runtime.resume",
  "runtime.stop",
  "runtime.restart",
  "runtime.reconnectBroker",
  "runtime.reconcile",
  "runtime.disableEntries",
  "runtime.enableEntries",
  "runtime.emergencyKill",
  "strategy.pause",
  "strategy.resume",
  "strategy.disable",
  "order.cancel",
  "order.cancelAll",
  "position.close",
  "position.closePartial",
  "position.modifyProtection",
  "position.closeAll",
  "position.management.pause",
  "position.management.resume",
  "breaker.reset",
  "alert.acknowledge",
  "incident.acknowledge",
  "config.validate",
  "config.apply",
  "config.rollback",
] as const satisfies readonly RuntimeCommandKind[];

const commandKindSchema = z.enum(commandKinds);
const commandCapabilitySchema = z
  .object({
    command: commandKindSchema,
    allowed: z.boolean(),
    reason: z.string().optional(),
    riskLevel: z.union([z.literal(1), z.literal(2), z.literal(3), z.literal(4)]),
    requiresReason: z.boolean(),
    requiresTypedConfirmation: z.boolean(),
    confirmationPhrase: z.string().optional(),
  })
  .strict();

const commandsSchema = z
  .object(
    Object.fromEntries(commandKinds.map((kind) => [kind, commandCapabilitySchema.optional()])),
  )
  .strict()
  .superRefine((commands, ctx) => {
    for (const [key, capability] of Object.entries(commands)) {
      if (capability && capability.command !== key) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: [key, "command"],
          message: "Command key mismatch.",
        });
      }
    }
  });

const runtimeCapabilitiesSchema = z
  .object({
    revision: z.number().int().nonnegative(),
    generatedAt: z.string().datetime(),
    source: z.literal("LOCAL_RUNTIME"),
    commands: commandsSchema,
  })
  .strict();

export function validateRuntimeCapabilities(raw: unknown): RuntimeCapabilities | null {
  const result = runtimeCapabilitiesSchema.safeParse(raw);
  return result.success ? (result.data as RuntimeCapabilities) : null;
}
