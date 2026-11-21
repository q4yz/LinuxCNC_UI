// The assistant (an AI agent using the machine through MCP).
import { AssistantConnectionSetting } from "../types/AssistantConnectionSetting";
import { CheckboxSetting } from "../types/CheckboxSetting";

export const assistantConnection = new AssistantConnectionSetting(
  "Assistant",
  "Connect an assistant",
  "assistant.connection",
  {
    description:
      "Add this machine to an AI assistant (Claude Code, Claude Desktop or any MCP client). " +
      "It can read everything and engage the E-stop; anything else is shown to you first.",
    order: 0,
  },
);

/** Read by the system service's MCP server (``assistant.allow_actions``). */
export const assistantAllowActions = new CheckboxSetting(
  "Assistant",
  "Let the assistant ask to run actions",
  "assistant.allow_actions",
  true,
  {
    description:
      "Homing, MDI, programs, heaters, outputs, calibrations, file changes: each one appears in the " +
      "assistant panel and runs only when you approve it. Off: the assistant only reads and can engage the E-stop.",
    order: 1,
  },
);
