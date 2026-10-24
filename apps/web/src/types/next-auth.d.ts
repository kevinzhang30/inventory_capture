import "next-auth";
import "next-auth/jwt";

declare module "next-auth" {
  interface Session {
    groups: string[];
    error?: string;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    idToken?: string;
    refreshToken?: string;
    expiresAt?: number;
    groups?: string[];
    error?: string;
  }
}
