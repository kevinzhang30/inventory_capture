import "server-only";

export const config = {
  apiBaseUrl: (process.env.API_BASE_URL ?? "http://localhost:8080").replace(/\/$/, ""),
  authMode: (process.env.AUTH_MODE ?? "dev") as "dev" | "cognito",
  cognito: {
    clientId: process.env.COGNITO_CLIENT_ID ?? "",
    clientSecret: process.env.COGNITO_CLIENT_SECRET ?? "",
    issuer: process.env.COGNITO_ISSUER ?? "",
  },
};

export const DEV_IDENTITY_COOKIE = "dev_identity";
export const DEFAULT_DEV_IDENTITY = { user: "dev-user", groups: ["operator", "reviewer", "admin"] };
