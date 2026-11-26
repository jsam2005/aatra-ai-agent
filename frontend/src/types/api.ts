// Mirrors the backend's Pydantic response models (app/schemas/api.py).

export type Route =
  | "knowledge_base"
  | "backend_read"
  | "backend_action"
  | "pending_confirmation"
  | "escalation"
  | "direct"
  | "error";

export type ActionStatus = "pending" | "confirmed" | "failed" | "cancelled" | "expired";
export type Rating = "up" | "down";

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details: Record<string, unknown> };
}

export interface Citation {
  id: number;
  title: string;
}

export interface ToolCall {
  tool_name: string;
  status: "success" | "error" | "pending_confirmation";
  arguments: Record<string, unknown>;
  duration_ms: number | null;
}

export interface PendingAction {
  id: number;
  tool_name: string;
  summary: string;
  status: ActionStatus;
  expires_at: string;
  result: Record<string, unknown> | null;
}

export interface Feedback {
  id: number;
  message_id: number;
  rating: Rating;
  comment: string | null;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  route: Route | null;
  citations: Citation[];
  tool_calls: ToolCall[];
  request_id: string | null;
  provider: string | null;
  model: string | null;
  degraded: boolean;
  fallback_reason: string | null;
  latency_ms: number | null;
  model_calls: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  actions: PendingAction[];
  cards: ResponseCard[];
  feedback: Feedback | null;
}

/** Structured views of tool results; the backend copies only whitelisted fields. */
export type ResponseCard =
  | { type: "subscription"; data: { plan?: string; price?: string; interval?: string; seats?: number; status?: string; current_period_end?: string; cancel_at_period_end?: boolean } }
  | { type: "invoices"; data: { invoices: { number: string; amount: string; status: string; issued_on: string }[] } }
  | {
      type: "payment_issue";
      data: {
        none?: boolean;
        invoice_number?: string;
        amount?: string;
        failed_attempts?: number;
        last_decline_code?: string | null;
        retries_remaining?: number;
        payment_method?: { brand: string; last4: string; expires: string; is_expired: boolean } | null;
        recommended_action?: "update_payment_method" | "retry_payment" | "escalate_to_human";
      };
    }
  | { type: "password_reset"; data: { sent_to?: string; link_valid_for?: string; already_sent_recently?: boolean; simulated?: boolean } }
  | { type: "ticket"; data: { ticket_reference?: string; priority?: string; status?: string; already_open?: boolean } };

export interface Conversation {
  id: number;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
  pending_actions: PendingAction[];
}

export interface ChatResponse {
  conversation_id: number;
  user_message: Message;
  reply: Message;
  pending_actions: PendingAction[];
}

export interface ActionResolution {
  action: PendingAction;
  message: Message;
}

export interface Article {
  id: number;
  title: string;
  content: string;
  category: string;
  tags: string[];
  is_published: boolean;
  created_at: string;
  updated_at: string;
}

export type ArticleInput = Pick<Article, "title" | "content" | "category" | "tags" | "is_published">;

export interface SearchHit {
  id: number;
  title: string;
  category: string;
  score: number;
  snippet: string;
}

export interface RatingStats {
  up: number;
  down: number;
  satisfaction: number | null;
}

export interface FeedbackSummary extends RatingStats {
  total: number;
  by_route: (RatingStats & { route: Route | null })[];
  by_tool: (RatingStats & { tool_name: string })[];
}

export interface Health {
  status: string;
  llm_provider: string;
  llm_model: string | null;
  fallback_provider: string | null;
}

export interface FeedbackItem extends Feedback {
  route: Route | null;
  message_excerpt: string;
}

export interface AnalyticsOverview {
  conversations: number;
  responses: number;
  degraded_responses: number;
  avg_latency_ms: number | null;
  responses_by_route: { route: Route | null; count: number }[];
  tools: { tool_name: string; calls: number; succeeded: number; errors: number; awaiting_confirmation: number; avg_duration_ms: number | null }[];
  feedback_by_day: { date: string; up: number; down: number }[];
}
