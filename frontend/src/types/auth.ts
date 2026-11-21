export type UserRole = "user" | "admin";

export interface AuthUser {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  phone_number: string;
  role: UserRole;
  date_joined: string;
}

export interface LoginResponse {
  access: string;
  refresh: string;
  user: AuthUser;
}

export interface RegisterPayload {
  email: string;
  password: string;
  password2: string;
  first_name?: string;
  last_name?: string;
  phone_number?: string;
}

export type ProfileUpdatePayload = Partial<
  Pick<AuthUser, "first_name" | "last_name" | "phone_number">
>;

export interface ChangePasswordPayload {
  old_password: string;
  new_password: string;
}
