// Typed client for the FastAPI backend. All business rules live on the server; this module only
// moves data. The base URL is relative: Vite proxies it in development, FastAPI serves it in production.
import type {
  ActionResolution,
  AnalyticsOverview,
  ApiErrorBody,
  Article,
  ArticleInput,
  ChatResponse,
  Conversation,
  ConversationDetail,
  Feedback,
  FeedbackItem,
  FeedbackSummary,
  Health,
  Page,
  Rating,
  SearchHit,
} from "../types/api";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  userId?: number;
  adminKey?: string;
}

async function request<T>(path: string, { method = "GET", body, userId, adminKey }: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (userId !== undefined) headers["X-User-Id"] = String(userId);
  if (adminKey) headers["X-Admin-Key"] = adminKey;

  let res: Response;
  try {
    res = await fetch(BASE + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the server. Is the backend running?");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = (data as ApiErrorBody | null)?.error;
    throw new ApiError(res.status, err?.code ?? "http_error", err?.message ?? `Request failed (${res.status})`, err?.details);
  }
  return data as T;
}

const qs = (params: Record<string, string | number | boolean | undefined>) => {
  const s = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && s.set(k, String(v)));
  const str = s.toString();
  return str ? `?${str}` : "";
};

export const api = {
  health: () => request<Health>("/health"),

  // chat & conversations (customer)
  chat: (userId: number, message: string, conversationId?: number) =>
    request<ChatResponse>("/api/v1/chat", { method: "POST", userId, body: { message, conversation_id: conversationId ?? null } }),
  conversations: (userId: number) => request<Page<Conversation>>("/api/v1/conversations?limit=50", { userId }),
  conversation: (userId: number, id: number) => request<ConversationDetail>(`/api/v1/conversations/${id}`, { userId }),
  deleteConversation: (userId: number, id: number) => request<void>(`/api/v1/conversations/${id}`, { method: "DELETE", userId }),

  // human-in-the-loop actions (customer)
  confirmAction: (userId: number, id: number) => request<ActionResolution>(`/api/v1/actions/${id}/confirm`, { method: "POST", userId }),
  cancelAction: (userId: number, id: number) => request<ActionResolution>(`/api/v1/actions/${id}/cancel`, { method: "POST", userId }),

  // feedback (customer)
  rate: (userId: number, messageId: number, rating: Rating) =>
    request<Feedback>(`/api/v1/messages/${messageId}/feedback`, { method: "PUT", userId, body: { rating } }),

  // knowledge base (reads are public; writes need the admin key)
  articles: (adminKey: string, params: { q?: string; category?: string } = {}) =>
    request<Page<Article>>(`/api/v1/kb/articles${qs({ ...params, limit: 100 })}`, { adminKey }),
  searchArticles: (q: string) => request<SearchHit[]>(`/api/v1/kb/articles/search${qs({ q, limit: 10 })}`),
  createArticle: (adminKey: string, body: ArticleInput) => request<Article>("/api/v1/kb/articles", { method: "POST", adminKey, body }),
  updateArticle: (adminKey: string, id: number, body: Partial<ArticleInput>) =>
    request<Article>(`/api/v1/kb/articles/${id}`, { method: "PATCH", adminKey, body }),
  deleteArticle: (adminKey: string, id: number) => request<void>(`/api/v1/kb/articles/${id}`, { method: "DELETE", adminKey }),

  // analytics (admin)
  feedbackSummary: (adminKey: string) => request<FeedbackSummary>("/api/v1/feedback/summary", { adminKey }),
  recentFeedback: (adminKey: string) => request<Page<FeedbackItem>>("/api/v1/feedback?limit=6", { adminKey }),
  analyticsOverview: (adminKey: string) => request<AnalyticsOverview>("/api/v1/analytics/overview", { adminKey }),
};
