// The in-app assistant (system service, ``/api/v1/agent/chat`` and
// ``/config``). Wraps the generated ``AssistantService``; the API key is
// write-only — reads only say whether one is set.

import { AssistantService } from "../../generated/api/services/AssistantService";
import type { AssistantConfigResponse } from "../../generated/api/models/AssistantConfigResponse";
import type { ConversationResponse } from "../../generated/api/models/ConversationResponse";
import { CommandResult } from "../entities/common/CommandResult";
import { describeError, errorStatus } from "../core/error-format";

export interface AssistantConfig {
  configured: boolean;
  keySource: string;
  keyHint: string;
  model: string;
  effort: string;
  models: { id: string; label: string }[];
  efforts: string[];
}

export type ChatEntryRole = "user" | "assistant" | "tool" | "error";

export interface ChatEntry {
  id: string;
  role: ChatEntryRole;
  text: string;
  /** Epoch ms. */
  time: number;
  tool: string | null;
  status: string;
}

export interface AssistantConversation {
  id: string;
  busy: boolean;
  partial: string;
  model: string;
  entries: ChatEntry[];
}

function toConfig(wire: AssistantConfigResponse): AssistantConfig {
  return {
    configured: wire.configured,
    keySource: wire.key_source ?? "",
    keyHint: wire.key_hint ?? "",
    model: wire.model,
    effort: wire.effort,
    models: wire.models.map((m) => ({ id: m.id, label: m.label })),
    efforts: [...wire.efforts],
  };
}

const ROLES: readonly ChatEntryRole[] = ["user", "assistant", "tool", "error"];

export function toConversation(wire: ConversationResponse): AssistantConversation {
  return {
    id: wire.id,
    busy: wire.busy,
    partial: wire.partial ?? "",
    model: wire.model ?? "",
    entries: wire.entries.map((e) => ({
      id: e.id,
      role: ROLES.includes(e.role as ChatEntryRole) ? (e.role as ChatEntryRole) : "error",
      text: e.text,
      time: Math.round(e.time * 1000),
      tool: e.tool ?? null,
      status: e.status ?? "",
    })),
  };
}

/** Throws on transport failure. */
async function config(): Promise<AssistantConfig> {
  return toConfig(await AssistantService.getAssistantConfig());
}

async function updateConfig(change: { apiKey?: string; model?: string; effort?: string }): Promise<{ result: CommandResult; config?: AssistantConfig }> {
  const commandId = "assistant:config";
  try {
    const wire = await AssistantService.updateAssistantConfig({
      api_key: change.apiKey ?? null,
      model: change.model ?? null,
      effort: change.effort ?? null,
    });
    return { result: CommandResult.success({ commandId }), config: toConfig(wire) };
  } catch (err: unknown) {
    return { result: CommandResult.failure(describeError(err), { commandId, statusCode: errorStatus(err) }) };
  }
}

/** Start a reply. Throws (with ``errorStatus``: 404 unknown conversation, 409 busy, 412 no key). */
async function send(message: string, conversationId: string | null): Promise<AssistantConversation> {
  return toConversation(await AssistantService.sendAssistantMessage({ message, conversation_id: conversationId }));
}

async function conversation(id: string): Promise<AssistantConversation> {
  return toConversation(await AssistantService.getAssistantConversation(id));
}

async function stop(id: string): Promise<void> {
  try {
    await AssistantService.stopAssistantReply(id);
  } catch {
    // already finished / forgotten: nothing to stop
  }
}

async function forget(id: string): Promise<void> {
  try {
    await AssistantService.deleteAssistantConversation(id);
  } catch {
    // unknown already
  }
}

export const assistantFacade = Object.freeze({ config, updateConfig, send, conversation, stop, forget });

export default assistantFacade;
