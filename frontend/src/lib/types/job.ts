// Enums copied from openapi.json. Fields marked "assumed" are untyped in the schema (response bodies are `{}`).
export const EMPLOYMENT_TYPES = ['full_time', 'part_time', 'contract', 'temporary', 'intern'] as const;
export const WORK_MODES = ['onsite', 'hybrid', 'remote'] as const;
export const REQ_CATEGORIES = ['skills', 'experience', 'education', 'certification', 'language', 'responsibility', 'other'] as const;
export const REQ_TYPES = ['mandatory', 'preferred'] as const;
export const IMPORTANCE = ['low', 'medium', 'high'] as const;

export type EmploymentType = (typeof EMPLOYMENT_TYPES)[number];
export type WorkMode = (typeof WORK_MODES)[number];
export type RequirementCategory = (typeof REQ_CATEGORIES)[number];
export type RequirementType = (typeof REQ_TYPES)[number];
export type Importance = (typeof IMPORTANCE)[number];

export interface JobInput {
  title: string;
  description: string;
  department?: string | null;
  employment_type: EmploymentType;
  work_mode: WorkMode;
  location?: string | null;
  openings?: number;
}

export interface Job extends JobInput {
  id: string;
  status: string; // assumed: draft | active | paused | closed | archived (README lifecycle)
  created_at?: string;
}

export interface RequirementInput {
  category: RequirementCategory;
  name: string;
  requirement_type: RequirementType;
  importance: Importance;
  weight?: number; // 0..1, preferred only; mandatory must be 0
  is_mandatory: boolean;
}
export interface Requirement extends RequirementInput { id: string }
