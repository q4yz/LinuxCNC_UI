// The assistant: the in-app chat (Claude, with an Anthropic API key) and
// outside assistants connecting through MCP. Both use the same tools,
// role and approvals.
import { defineAsyncComponent } from "vue";

import { CheckboxSetting } from "../types/CheckboxSetting";
import { PanelSetting } from "../types/PanelSetting";

// Lazy: the panels' .vue files load only when the Settings view renders them.
const SettingAssistantChat = defineAsyncComponent(() => import("../components/SettingAssistantChat.vue"));
const SettingAssistantConnection = defineAsyncComponent(() => import("../components/SettingAssistantConnection.vue"));

export const assistantChat = new PanelSetting("Assistant", "In-app assistant (Claude)", "assistant.chat", SettingAssistantChat, {
  description:
    "The chat panel on the right answers with Claude once an Anthropic API key is set. The key stays on this machine " +
    "(never shown again, never sent to the browser); usage is billed to that key's Anthropic account.",
  order: 0,
});

export const assistantConnection = new PanelSetting(
  "Assistant",
  "Connect an outside assistant",
  "assistant.connection",
  SettingAssistantConnection,
  {
    description:
      "Add this machine to an AI assistant on your computer (Claude Code, Claude Desktop or any MCP client). " +
      "It can read everything and engage the E-stop; anything else is shown to you first.",
    order: 1,
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
      "assistant panel and runs only when you approve it. Off: the assistant only reads and can engage the E-stop. " +
      "Applies to the in-app chat and to outside assistants.",
    order: 2,
  },
);
