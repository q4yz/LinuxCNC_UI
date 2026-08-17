import { BaseThreadService as ApiBaseThreadService } from "../../generated/api/services/BaseThreadService";
import { Snapshot } from "../entities/baseThread/Snapshot";
import { toSnapshot } from "../mappers/baseThreadMapper";

export class BaseThreadService {
  /**
   * Fetch the latest base thread snapshot from the API and map it
   * into a fully typed Snapshot domain entity.
   */
  static async fetchSnapshot(): Promise<Snapshot> {
    try {
      const wire = await ApiBaseThreadService.getBaseThreadSnapshot();
      return toSnapshot(wire);
    } catch (err: unknown) {
      // Log the error but let the caller (the Pinia store) handle 
      // the UI error state rather than returning a half-built object.
      console.error("[BaseThreadService] Failed to fetch snapshot", err);
      throw err;
    }
  }
}