export interface AuthTenant {
  id: number;
  name: string;
  slug?: string;
}

export interface AuthUser {
  id: number;
  email: string;
  role: string;
  tenant: AuthTenant | null;
}

export interface RegisterResponse {
  id: number;
  email: string;
  token: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
}
