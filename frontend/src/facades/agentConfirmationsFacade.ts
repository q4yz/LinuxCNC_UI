// The assistant's actions waiting for the operator (system service,
// ``/api/v1/agent/confirmations``). Wraps the generated
// ``AssistantService``; the entity is camelCase and time is in ms.

import { AssistantService } from "../../generated/api/services/AssistantService";
import type { AgentConfirmationResponse } from "../../generated/api/models/AgentConfirmationResponse";
import { CommandResult } from "../entities/common/CommandResult";
import { describeError, errorStatus } from "../core/error-format";

export type AgentDecision = "pending" | "approved" | "denied" | "expired";

export interface AgentConfirmation {
  id: string;
  tool: string;
  summary: string;
  method: string;
  path: string;
  arguments: Record<string, unknown>;
  permission: string;
  decision: AgentDecision;
  reason: string;
  /** Epoch ms. */
  created: number;
  expires: number;
}

const DECISIONS: readonly AgentDecision[] = ["pending", "approved", "denied", "expired"];

export function toConfirmation(wire: AgentConfirmationResponse): AgentConfirmation {
  const decision = DECISIONS.includes(wire.decision as AgentDecision) ? (wire.decision as AgentDecision) : "expired";
  return {
    id: wire.id,
    tool: wire.tool,
    summary: wire.summary,
    method: wire.method,
    path: wire.path,
    arguments: (wire.arguments ?? {}) as Record<string, unknown>,
    permission: wire.permission,
    decision,
    reason: wire.reason ?? "",
    created: Math.round(wire.created * 1000),
    expires: Math.round(wire.expires * 1000),
  };
}

/** Pending and recently decided requests. Throws on transport failure. */
async function list(): Promise<AgentConfirmation[]> {
  const response = await AssistantService.listAgentConfirmations();
  return (response?.confirmations ?? []).map(toConfirmation);
}

async function decide(id: string, approve: boolean, reason = ""): Promise<CommandResult> {
  const commandId = `agent:${approve ? "approve" : "deny"}:${id}`;
  try {
    const body = reason ? { reason } : null;
    if (approve) await AssistantService.approveAgentConfirmation(id, body);
    else await AssistantService.denyAgentConfirmation(id, body);
    return CommandResult.success({ commandId });
  } catch (err: unknown) {
    return CommandResult.failure(describeError(err), { commandId, statusCode: errorStatus(err) });
  }
}

export interface AgentStatus {
  /** The MCP server's path on this host (``/mcp``). */
  mcpPath: string;
  running: boolean;
  actionsAllowed: boolean;
  /** Tools offered now, per backend (``machine`` / ``system``). */
  tools: Record<string, number>;
  toolsNeedingApproval: number;
  pending: number;
}

/** The assistant's MCP server. Throws on transport failure. */
async function status(): Promise<AgentStatus> {
  const wire = await AssistantService.getAgentStatus();
  return {
    mcpPath: wire.mcp_path,
    running: wire.running,
    actionsAllowed: wire.actions_allowed,
    tools: (wire.tools ?? {}) as Record<string, number>,
    toolsNeedingApproval: wire.tools_needing_approval ?? 0,
    pending: wire.pending ?? 0,
  };
}

export const agentConfirmationsFacade = Object.freeze({
  list,
  status,
  approve: (id: string, reason = "") => decide(id, true, reason),
  deny: (id: string, reason = "") => decide(id, false, reason),
});

export default agentConfirmationsFacade;
