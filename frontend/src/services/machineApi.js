// Small compatibility surface for legacy shell consumers that still send
// MDI commands.  It intentionally avoids importing the generated machine
// service: when the optional machine backend module is removed, codegen no
// longer emits that class, but the shell must remain buildable.

export const machineApi = {
  async runMdiCommand(requestBody) {
    const response = await fetch("/api/v1/modules/machine/mdi", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const payload = await response.json();
        detail = payload?.detail ?? detail;
      } catch (_) {
        // Keep the HTTP status when the server returned no JSON body.
      }
      throw new Error(`MDI request failed: ${response.status} ${detail}`);
    }
    return response.json();
  },
};

export default machineApi;
