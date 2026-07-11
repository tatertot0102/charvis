// TypeScript mirror of app/dashboard/contracts.py — keep in sync with the backend.

export type DashboardMode =
  | "idle" | "pre_event" | "travel" | "deep_work" | "deadline" | "crisis";

export type TruthBadge =
  | "verified" | "remembered" | "likely" | "inferred" | "conflicted" | "stale";

export type SectionId =
  | "hero" | "priority" | "today" | "working_memory" | "notifications" | "approvals";

export type SourceStateValue =
  | "connected" | "disconnected" | "unavailable" | "permission_missing"
  | "token_expired" | "request_failed" | "coming_later";

export interface EvidenceRef {
  source: string;
  provider_object_id?: string | null;
  text: string;
}

export interface SourceStatus {
  name: string;
  label: string;
  state: SourceStateValue;
  connected: boolean;
  healthy: boolean;
  detail: string;
  capabilities: string[];
  placeholder: boolean;
}

export interface HeroState {
  present: boolean;
  kind: string;
  title: string;
  when?: string | null;
  countdown_seconds?: number | null;
  location?: string | null;
  people: string[];
  context?: string | null;
  related_emails: EvidenceRef[];
  prep_checklist: string[];
  badges: TruthBadge[];
  evidence: EvidenceRef[];
}

export interface PriorityItem {
  title: string;
  reason: string;
  badge: TruthBadge;
  confidence: number;
  urgent: boolean;
  context?: string | null;
  evidence: EvidenceRef[];
}

export interface PriorityState {
  top?: PriorityItem | null;
  secondary: PriorityItem[];
}

export interface TodayItem {
  title: string;
  when?: string | null;
  detail?: string | null;
  badge: TruthBadge;
  provider_object_id?: string | null;
}

export interface TodayState {
  events: TodayItem[];
  commitments: TodayItem[];
  email_events: TodayItem[];
  conflicts: string[];
  missing_calendar: string[];
}

export interface WorkingMemoryItem {
  label: string;
  value: string;
  badge?: TruthBadge | null;
  done: boolean;
}

export interface NotificationItem {
  kind: string;
  text: string;
  severity: "info" | "warn" | "urgent";
  href?: string | null;
}

export interface ApprovalSummary {
  id: number;
  action_type: string;
  summary: string;
  target_event_id?: string | null;
  confidence: number;
  item_count: number;
  required_phrase: string;
  expires_at?: string | null;
  evidence: EvidenceRef[];
}

export interface DashboardSection {
  id: SectionId;
  visible: boolean;
  collapsed: boolean;
  size: "sm" | "md" | "lg";
  order: number;
}

export interface LayoutState {
  mode: DashboardMode;
  sections: DashboardSection[];
  focus?: string | null;
  last_workspace?: string | null;
}

export interface TopStatus {
  server_time: string;
  next_event_title?: string | null;
  next_event_countdown_seconds?: number | null;
  brain_healthy: boolean;
  sources: SourceStatus[];
}

export interface DashboardState {
  generated_at: string;
  mode: DashboardMode;
  focus?: string | null;
  top_status: TopStatus;
  hero: HeroState;
  priority: PriorityState;
  today: TodayState;
  working_memory: WorkingMemoryItem[];
  notifications: NotificationItem[];
  approvals: ApprovalSummary[];
  layout: LayoutState;
  sources: SourceStatus[];
}

export interface EntityWorkspace {
  entity_type: string;
  id: string;
  title: string;
  summary: string;
  events: TodayItem[];
  emails: EvidenceRef[];
  commitments: string[];
  memory: string[];
  people: string[];
  waiting: string[];
  conflicts: string[];
  evidence: EvidenceRef[];
  badges: TruthBadge[];
}

export interface LayoutCommand {
  action: string;
  section?: SectionId;
  order?: SectionId[];
  size?: string;
  focus?: string | null;
  workspace?: string;
}
