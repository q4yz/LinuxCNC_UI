// Debug: probe the openapi client to see what listActive returns.
import { ModulesMachineconfigService } from './generated/api/index.ts';

const result = await ModulesMachineconfigService.listActiveApiV1ModulesMachineconfigActiveGet();
console.log('type:', typeof result);
console.log('isArray:', Array.isArray(result));
console.log('keys:', Object.keys(result));
console.log('machine_name:', result.machine_name);
console.log('files:', result.files);
console.log('files length:', result.files?.length);
