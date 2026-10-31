// Bed mesh facade (`.agent/component/bed_mesh.md`).
//
//   * meshes (files)          — system service, ``/api/v1/modules/bedmesh``
//   * compensation on / off   — machine backend, ``/api/v1/bedmesh/enable``
//     (a HAL pin: only while a LinuxCNC session runs)
//
// Thin pass-through: callers catch and report errors via describeError.

import { BedmeshService, ModulesBedmeshService } from "../../generated/api/index";
import type {
  BedMeshCreateRequest,
  BedMeshDefaults,
  BedMeshGrid,
  BedMeshListResponse,
} from "../../generated/api/index";

export type { BedMeshDefaults, BedMeshGrid, BedMeshListResponse };

export const bedMeshFacade = {
  list: (): Promise<BedMeshListResponse> => ModulesBedmeshService.listBedMeshes(),
  defaults: (): Promise<BedMeshDefaults> => ModulesBedmeshService.getBedMeshDefaults(),
  read: (name: string): Promise<BedMeshGrid> => ModulesBedmeshService.readBedMesh(name),
  create: (request: BedMeshCreateRequest): Promise<BedMeshGrid> =>
    ModulesBedmeshService.createBedMesh(request),
  save: (grid: BedMeshGrid): Promise<BedMeshGrid> => ModulesBedmeshService.saveBedMesh(grid.name, grid),
  remove: (name: string): Promise<BedMeshListResponse> => ModulesBedmeshService.deleteBedMesh(name),
  activate: (name: string): Promise<BedMeshListResponse> => ModulesBedmeshService.activateBedMesh(name),
  isEnabled: async (): Promise<boolean> => (await BedmeshService.getBedMeshEnable()).enabled,
  setEnabled: async (enabled: boolean): Promise<boolean> =>
    (await BedmeshService.setBedMeshEnable({ enabled })).enabled,
};

export default bedMeshFacade;
