import { apiClient } from "./client";
import type {
  AuthUser,
  ChangePasswordPayload,
  LoginResponse,
  ProfileUpdatePayload,
  RegisterPayload,
} from "../types/auth";

export async function registerRequest(payload: RegisterPayload): Promise<AuthUser> {
  const { data } = await apiClient.post<AuthUser>("/auth/register/", payload);
  return data;
}

export async function loginRequest(email: string, password: string): Promise<LoginResponse> {
  const { data } = await apiClient.post<LoginResponse>("/auth/login/", { email, password });
  return data;
}

export async function logoutRequest(refreshToken: string): Promise<void> {
  await apiClient.post("/auth/logout/", { refresh: refreshToken });
}

export async function fetchProfileRequest(): Promise<AuthUser> {
  const { data } = await apiClient.get<AuthUser>("/auth/profile/");
  return data;
}

export async function updateProfileRequest(payload: ProfileUpdatePayload): Promise<AuthUser> {
  const { data } = await apiClient.patch<AuthUser>("/auth/profile/", payload);
  return data;
}

export async function changePasswordRequest(payload: ChangePasswordPayload): Promise<void> {
  await apiClient.post("/auth/change-password/", payload);
}
