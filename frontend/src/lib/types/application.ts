// From openapi.json. Statuses and eligibility values are the backend's, not ours.
export const APP_STATUSES = ['applied', 'processing', 'analyzed', 'shortlisted', 'rejected', 'withdrawn'] as const;
export type AppStatus = (typeof APP_STATUSES)[number];
export type Eligibility = 'eligible' | 'needs_review' | 'potentially_ineligible';
export type DecisionAgentId = 'balanced' | 'bar_raiser' | 'growth_potential' | 'risk_guardian';
export type DecisionOutcome = 'strong_advance' | 'advance' | 'review' | 'hold' | 'pass';

export interface DecisionAgentMeta {
  id: DecisionAgentId;
  name: string;
  short_name: string;
  tagline: string;
}

export interface AgentDecision {
  agent_id: DecisionAgentId;
  agent_name: string;
  decision: DecisionOutcome;
  threshold_outcome?: 'accept' | 'reject' | 'review' | null;
  confidence: number;
  summary: string;
  next_step: string;
  key_factors: string[];
  risk_flags: string[];
  mode?: string;
}

export interface FraudRiskSummary {
  score: number;
  level: 'low' | 'medium' | 'high';
  flags: string[];
}

export const DEFAULT_DECISION_AGENTS: DecisionAgentMeta[] = [
  {
    id: 'balanced',
    name: 'Balanced Hiring Manager',
    short_name: 'Balanced',
    tagline: 'Weighs overall fit, mandatory requirements, skills, and verification evenly.'
  },
  {
    id: 'bar_raiser',
    name: 'Strict Bar Raiser',
    short_name: 'Bar Raiser',
    tagline: 'High technical bar requiring strong scores, mandatory pass, and verified proof.'
  },
  {
    id: 'growth_potential',
    name: 'Growth & Potential Scout',
    short_name: 'Growth Scout',
    tagline: 'Prioritizes strong skills, projects, and trajectory even with minor gaps.'
  },
  {
    id: 'risk_guardian',
    name: 'Verification & Risk Guard',
    short_name: 'Risk Guard',
    tagline: 'Prioritizes profile authenticity, data completeness, and clean verification.'
  }
];

export const DECISION_OUTCOME_LABEL: Record<DecisionOutcome, string> = {
  strong_advance: 'Strong Advance',
  advance: 'Advance',
  review: 'Manual Review',
  hold: 'Hold',
  pass: 'Do Not Advance'
};

export interface RankedItem {
  candidate_name?: string; application_id: string; application_created_at?: string; score: number | string | null; eligibility?: Eligibility;
  skills_score?: number | string | null; data_completeness?: number | string; status?: string; verification_statuses?: string[]; rank: number;
  decision?: AgentDecision | null;
  agent_decisions?: Record<string, AgentDecision>;
}
export interface RankingPage {
  run_id: string | null;
  total_count: number;
  offset: number;
  limit: number;
  items: RankedItem[];
  scoring_version?: string | null;
  algorithm_version?: string | null;
  decision_agent?: DecisionAgentId;
  available_decision_agents?: DecisionAgentMeta[];
}

export interface CategoryAnalysis { status: 'known' | 'unknown' | 'not_applicable'; match?: number | string | null; weight: number | string; weighted_contribution?: number | string | null; notes?: string[] }
export interface Analysis {
  overall_score?: number | string | null; mandatory_coverage_pct?: number | string | null;
  application_id: string; score: number | string | null; score_percent: number | string | null; score_lower_bound: number | string | null; score_upper_bound: number | string | null;
  data_completeness: number | string | null; eligibility: Eligibility | null; mandatory_results: unknown[]; categories: Record<string, CategoryAnalysis>;
  review_signals: string[]; evidence_groups: unknown[]; scoring_version: string | null; algorithm_version: string | null;
  verification_detail: {
    overall_status: string;
    checks: { check_type: string; status: string; signal: string; details?: Record<string, unknown> }[];
    fraud_risk?: FraudRiskSummary | null;
  };
  candidate: { id: string | null; full_name?: string | null; display_name?: string | null; email: string | null; phone: string | null; links: Record<string, unknown>; profile: Record<string, unknown> };
  resume: {
    file_name: string;
    content_type: string;
    size_bytes: number;
    page_count?: number | null;
    uploaded_at: string;
    parse_status: string;
    parser_version?: string | null;
    extraction_version?: string | number | null;
    overall_confidence?: number | null;
    extraction_method?: string | null;
    ai_engine?: string | null;
    ai_model?: string | null;
    prompt_version?: string | null;
    ocr_used?: boolean;
    ocr_confidence?: number | null;
    warnings?: string[];
  } | null;
  application: { id: string; job_id: string; job_title: string; status: string; status_history: unknown[] };
  explanation: { deterministic_summary: string[]; ai_summary: Record<string, unknown> | null; ai_status: string; disclaimer: string };
  decision?: AgentDecision | null;
  agent_decisions?: Record<string, AgentDecision>;
}
export const ELIGIBILITY_LABEL: Record<Eligibility, string> = {
  eligible: 'Meets mandatory requirements',
  needs_review: 'Needs review',
  potentially_ineligible: 'May not meet mandatory requirements (review manually)'
};
