// Demo-only: the four seeded customers of the fictional client "Nimbus" (scripts/seed.py).
// Switching sets the mock X-User-Id header; the backend still enforces per-user access.
export interface DemoCustomer {
  id: number;
  name: string;
  email: string;
  plan: string;
  scenario: string;
}

export const DEMO_CUSTOMERS: DemoCustomer[] = [
  { id: 1, name: "Asha Raman", email: "asha@example.com", plan: "Pro", scenario: "Healthy account" },
  { id: 2, name: "Ben Carter", email: "ben@example.com", plan: "Starter", scenario: "Expired card" },
  { id: 3, name: "Chen Wei", email: "chen@example.com", plan: "Business", scenario: "Retryable payment" },
  { id: 4, name: "Diana Okafor", email: "diana@example.com", plan: "Pro", scenario: "Retry limit exhausted" },
];

export const DEFAULT_ADMIN_KEY = "nimbus-admin-demo";

export const initials = (name: string) => name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();
