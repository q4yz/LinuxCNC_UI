// Accounts and logins (#131): ``/api/v1/auth`` and ``/api/v1/users`` on
// the system backend. Reads and commands throw an ``Error`` whose
// message is the backend's reason (shown to the operator as is).
import { AuthService } from "../../generated/api/services/AuthService";
import type { CurrentUserResponse } from "../../generated/api/models/CurrentUserResponse";
import type { LoginResponse } from "../../generated/api/models/LoginResponse";
import type { UserListResponse } from "../../generated/api/models/UserListResponse";
import type { UserResponse } from "../../generated/api/models/UserResponse";
import { describeError } from "../core/error-format";

export type { CurrentUserResponse, LoginResponse, UserListResponse, UserResponse };

async function call<T>(action: () => Promise<T>): Promise<T> {
  try {
    return await action();
  } catch (err: unknown) {
    throw new Error(describeError(err));
  }
}

export const authFacade = {
  me: () => call(() => AuthService.authMe()),
  login: (username: string, password: string) => call(() => AuthService.authLogin({ username, password })),
  changePassword: (currentPassword: string, newPassword: string) =>
    call(() => AuthService.authChangePassword({ current_password: currentPassword, new_password: newPassword })),
  logoutEverywhere: () => call(() => AuthService.authLogoutEverywhere()),
  listUsers: () => call(() => AuthService.listUsers()),
  createUser: (username: string, password: string, role: string) =>
    call(() => AuthService.createUser({ username, password, role })),
  updateUser: (name: string, change: { role?: string; password?: string }) =>
    call(() => AuthService.updateUser(name, change)),
  deleteUser: (name: string) => call(() => AuthService.deleteUser(name)),
};

export default authFacade;
