export type Language = "RU" | "KZ" | "EN";
export type Channel = "agent chat" | "voice call";
export type Status = "queued" | "running" | "completed" | "failed";
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
export interface Message {
  id: string;
  position: number;
  timestamp: string;
  speaker: "client" | "operator" | "bot" | "system";
  text: string;
}
export interface OrganizerRecord {
  conversation_id: string;
  channel: Channel;
  language: Language;
  transcript: Omit<Message, "id" | "position">[];
  audio_url: string | null;
}
export interface ImportSummary {
  group_id: string;
  received: number;
  created: number;
  new_versions: number;
  unchanged: number;
  conversation_ids: string[];
}
export interface Conversation {
  id: string;
  external_id: string;
  source: "dataset" | "upload";
  group_id: string;
  language: Language;
  channel: Channel;
  current_transcript_version_id: string;
  message_count: number;
  latest_evaluation: {
    id: string;
    status: Status;
    original_total: number | null;
    final_total: number | null;
    created_at: string;
  } | null;
}
export interface ConversationDetail extends Conversation {
  transcript_version_id: string;
  audio_url: string | null;
  messages: Message[];
}
export interface ScalePoint {
  value: number;
  description: string;
}
export interface Criterion {
  id: string;
  name: string;
  instruction: string;
  type: "binary" | "scale" | "flag";
  weight: number;
  allow_na: boolean;
  na_rule: string | null;
  scale: ScalePoint[] | null;
  section: string | null;
}
export interface ChecklistSummary {
  id: string;
  name: string;
  latest_version_id: string;
  latest_version_number: number;
}
export interface ChecklistVersion {
  id: string;
  checklist_id: string;
  name: string;
  version_number: number;
  created_at: string;
  criteria: Criterion[];
}
export interface ChecklistDetail {
  id: string;
  name: string;
  current_version: ChecklistVersion;
  versions: ChecklistVersion[];
}
export type Evidence =
  | { kind: "message"; message_id: string }
  | { kind: "range"; start_message_id: string; end_message_id: string };
export interface CriterionAssessment {
  criterion_id: string;
  applicability: "applicable" | "not_applicable";
  answer: boolean | number | null;
  weight: number;
  base_points: number;
  effective_weight: number;
  effective_points: number;
  explanation: string;
  evidence: Evidence[];
  review_required: boolean;
  review_reasons: string[];
}
export interface Assessment {
  total: number | null;
  no_applicable_reason: string | null;
  gross_error: boolean | null;
  criteria: CriterionAssessment[];
  sections: {
    name: string;
    base_points: number;
    applicable_weight: number;
    total: number | null;
  }[];
}
export interface SafeError {
  code: string;
  message: string;
  details: { loc: (string | number)[]; type: string }[];
}
export interface Provenance {
  provider: string;
  model_requested: string;
  model_reported: string | null;
  prompt_version: string;
  duration_ms: number;
  estimated_cost_usd: number | null;
  usage: {
    request_count: number;
    input_tokens: number | null;
    output_tokens: number | null;
    total_tokens: number | null;
    cached_input_tokens: number | null;
    reasoning_output_tokens: number | null;
  };
}
export interface Evaluation {
  id: string;
  conversation_id: string;
  transcript_version_id: string;
  checklist_version_id: string;
  status: Status;
  revision: number;
  created_at: string;
  completed_at: string | null;
  original: Assessment | null;
  final: Assessment | null;
  review_required: boolean;
  review_reasons: string[];
  provenance: Provenance | null;
  error: SafeError | null;
}
export interface ProviderCriterionResult {
  criterion_id: string;
  applicability: "applicable" | "not_applicable";
  answer: boolean | number | null;
  explanation: string;
  evidence: Evidence[];
  review_reasons: string[];
}
export interface Appeal {
  id: string;
  evaluation_id: string;
  criterion_id: string;
  comment: string;
  status: "open" | "resolved";
  base_revision: number;
  current_revision: number;
  created_at: string;
  original: CriterionAssessment;
  current: CriterionAssessment;
  decision: {
    id: string;
    appeal_id: string;
    action: "confirm" | "override";
    reason: string;
    expected_revision: number;
    created_at: string;
    result: ProviderCriterionResult;
  } | null;
}
export type Decision =
  | { action: "confirm"; reason: string; expected_revision: number }
  | {
      action: "override";
      reason: string;
      expected_revision: number;
      applicability: "applicable" | "not_applicable";
      answer: boolean | number | null;
      evidence: Evidence[];
    };
