// Turns the backend's extracted candidate data (untyped in OpenAPI) into a presentation model.
// Original data is never altered: `raw` keeps it for the Raw data tab and evidence stays attached to items.
import { isObj, num, humanize } from '$lib/utils';

export type Dict = Record<string, unknown>;
export interface Evidenced { evidence: string[]; confidence: number | null }
export interface Experience extends Evidenced { title: string | null; company: string | null; location: string | null; dates: string | null; current: boolean; bullets: string[] }
export interface Education extends Evidenced { degree: string | null; institution: string | null; period: string | null; grade: string | null; location: string | null }
export interface Project extends Evidenced { name: string | null; description: string | null; tech: string[]; url: string | null }
export interface Certification extends Evidenced { name: string | null; issuer: string | null; date: string | null; url: string | null }
export interface Skill { name: string; category: string }
export interface Link { label: string; url: string }
export interface Application { jobId: string | null; applicationId: string | null; jobTitle: string | null; status: string | null }
export interface Profile {
  name: string | null; headline: string | null; location: string | null; email: string | null; phone: string | null; links: Link[];
  summary: string | null; yearsExperience: string | null; skills: Skill[]; experience: Experience[]; education: Education[]; projects: Project[]; certifications: Certification[];
  applications: Application[];
  meta: {
    confidence: number | null;
    method: string | null;
    model: string | null;
    origin: string | null;
    parseStatus: string | null;
    promptVersion: string | null;
    schemaVersion: string | null;
    ocrUsed: boolean | null;
    warnings: string[];
  };
  identity: { status: string | null; checks: { label: string; status: string; note: string | null; details?: Dict }[] } | null;
  other: Dict;
  raw: unknown;
}

const unwrap = (v: unknown): unknown => (isObj(v) && 'value' in v ? unwrap(v.value) : v);
export const text = (v: unknown): string | null => {
  const x = unwrap(v);
  if (typeof x === 'string') return x.trim() || null;
  if (typeof x === 'number' && Number.isFinite(x)) return String(x);
  return null;
};
const pick = (o: Dict | null | undefined, keys: string[]): unknown => { if (o) for (const k of keys) if (o[k] !== undefined && o[k] !== null && o[k] !== '') return o[k]; return undefined; };
const arr = (v: unknown): unknown[] => {
  const x = unwrap(v);
  if (Array.isArray(x)) return x;
  if (isObj(x)) for (const y of Object.values(x)) if (Array.isArray(y)) return y;
  return [];
};
const texts = (v: unknown): string[] => {
  const x = unwrap(v);
  if (typeof x === 'string') return x.split(/\n|•|·(?=\s)/).map((s) => s.trim()).filter(Boolean);
  return arr(x).flatMap((i) => (isObj(i) ? [text(pick(i, ['text', 'description', 'name', 'value']))] : [text(i)])).filter((s): s is string => !!s);
};
const evidenceOf = (o: Dict): string[] => {
  const e = pick(o, ['evidence', 'evidence_text', 'source_text', 'source_excerpt', 'excerpt', 'source']);
  const x = unwrap(e);
  if (typeof x === 'string') return [x.trim()].filter(Boolean);
  return arr(x).flatMap((i) => (isObj(i) ? [text(pick(i, ['text', 'quote', 'excerpt', 'snippet', 'value']))] : [text(i)])).filter((s): s is string => !!s);
};
const confOf = (o: Dict) => num(unwrap(pick(o, ['confidence', 'extraction_confidence', 'score'])));
const base = (o: Dict): Evidenced => ({ evidence: evidenceOf(o), confidence: confOf(o) });
/** Entries may be objects or plain strings; strings become { text } so they still show up. */
const techOf = (v: unknown): string[] => { const x = unwrap(v); return typeof x === 'string' ? x.split(/[,;|•\n]/).map((t) => t.trim()).filter(Boolean) : texts(x); };
const items = (v: unknown): Dict[] => arr(v).map((x) => (isObj(x) ? x : typeof x === 'string' && x.trim() ? { text: x.trim() } : null)).filter((x): x is Dict => !!x);
const norm = (k: string) => k.toLowerCase().replace(/[^a-z0-9]/g, '');
const present = (v: unknown) => { const x = unwrap(v); return x !== undefined && x !== null && x !== '' && !(Array.isArray(x) && !x.length) && !(isObj(x) && !Object.keys(x).length); };
/** Breadth-first search through nested objects for the first key matching any alias (names compared ignoring case, _ and spaces). */
function deepFind(roots: unknown[], aliases: string[], maxDepth = 4): unknown {
  const want = new Set(aliases.map(norm));
  let level = roots.filter(isObj) as Dict[];
  for (let d = 0; d <= maxDepth && level.length; d++) {
    for (const o of level) for (const [k, v] of Object.entries(o)) if (want.has(norm(k)) && present(v)) return v;
    level = level.flatMap((o) => Object.values(o).map(unwrap).filter(isObj) as Dict[]);
  }
  return undefined;
}

const safeUrl = (u: string | null): string | null => {
  if (!u) return null;
  const withScheme = /^[a-z][a-z0-9+.-]*:/i.test(u) ? u : `https://${u}`;
  try { const p = new URL(withScheme); return p.protocol === 'http:' || p.protocol === 'https:' ? p.toString() : null; } catch { return null; }
};
const BRANDS: Record<string, string> = { linkedin: 'LinkedIn', github: 'GitHub', gitlab: 'GitLab', portfolio: 'Portfolio', website: 'Website', twitter: 'Twitter', kaggle: 'Kaggle' };
/** Category names: humanised, with short acronyms (ml, ai, nlp) upper-cased. */
export const niceCategory = (k: string) => humanize(k).split(' ').map((w) => (w.length <= 3 ? w.toUpperCase() : w)).join(' ');
const hostLabel = (url: string, hint?: string) => {
  if (hint) { const h = hint.replace(/_?url$/i, '').toLowerCase(); return BRANDS[h] ?? humanize(h || hint); }
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return url; }
};

function skillsOf(v: unknown): Skill[] {
  const out: Skill[] = []; const seen = new Set<string>();
  const add = (name: string | null, category: string) => { if (name && !seen.has(name.toLowerCase())) { seen.add(name.toLowerCase()); out.push({ name, category }); } };
  const x = unwrap(v);
  if (typeof x === 'string') for (const t of x.split(/[,;|\n•]/)) add(t.trim() || null, 'Skills');
  else if (Array.isArray(x)) for (const s of x) {
    if (isObj(s)) {
      const cat = text(pick(s, ['category', 'type', 'group'])) ?? 'Skills';
      const nested = pick(s, ['items', 'skills', 'list', 'values']);
      if (Array.isArray(unwrap(nested))) for (const n of unwrap(nested) as unknown[]) add(isObj(n) ? text(pick(n, ['name', 'skill', 'value'])) : text(n), cat);
      else add(text(pick(s, ['name', 'skill', 'value', 'label', 'text'])), cat);
    } else add(text(s), 'Skills');
  }
  else if (isObj(x)) for (const [k, group] of Object.entries(x)) for (const s of Array.isArray(unwrap(group)) ? (unwrap(group) as unknown[]) : [group]) add(isObj(s) ? text(pick(s, ['name', 'skill', 'value'])) : text(s), niceCategory(k));
  return out;
}

function linksOf(profile: Dict, root: Dict): Link[] {
  const out: Link[] = []; const seen = new Set<string>();
  const add = (raw: string | null, hint?: string) => { const url = safeUrl(raw); if (url && !seen.has(url)) { seen.add(url); out.push({ label: hostLabel(url, hint), url }); } };
  for (const src of [profile, root]) {
    const l = unwrap(src.links);
    if (isObj(l)) for (const [k, v] of Object.entries(l)) add(text(v), k);
    else if (Array.isArray(l)) for (const i of l) { if (isObj(i)) add(text(pick(i, ['url', 'link', 'href'])), text(pick(i, ['label', 'type', 'name'])) ?? undefined); else add(text(i)); }
    for (const k of ['linkedin', 'linkedin_url', 'github', 'github_url', 'portfolio', 'portfolio_url', 'website']) add(text(src[k]), k);
  }
  return out;
}

const CONSUMED = new Set(['id', 'fullname', 'displayname', 'name', 'candidatename', 'headline', 'currenttitle', 'currentrole', 'currentposition', 'professionaltitle', 'jobtitle', 'designation', 'title', 'position', 'location', 'city', 'address', 'email', 'phone', 'mobile', 'links', 'linkedin', 'linkedinurl', 'github', 'githuburl', 'portfolio', 'portfoliourl', 'website', 'summary', 'professionalsummary', 'about', 'objective', 'careerobjective', 'profilesummary', 'bio', 'skills', 'technicalskills', 'skillset', 'keyskills', 'competencies', 'coreskills', 'technologies', 'experience', 'workexperience', 'employment', 'experiences', 'workhistory', 'professionalexperience', 'employmenthistory', 'career', 'education', 'educations', 'educationhistory', 'academics', 'academicbackground', 'qualifications', 'projects', 'personalprojects', 'academicprojects', 'keyprojects', 'certifications', 'certificates', 'licenses', 'licensesandcertifications', 'courses', 'training', 'totalexperienceyears', 'yearsofexperience', 'experienceyears', 'totalexperience', 'extraction', 'meta', 'metadata', 'extractionconfidence', 'overallconfidence', 'confidence', 'extractionmethod', 'extractedby', 'method', 'parser', 'parserversion', 'model', 'aimodel', 'aiengine', 'llmmodel', 'dataorigin', 'origin', 'source', 'warnings', 'extractionwarnings', 'parsewarnings', 'promptversion', 'schemaversion', 'extractionversion', 'ocrused', 'ocrconfidence', 'resumeid', 'createdat', 'updatedat']);
/** Profile fields we do not map to a section, so no extracted data is ever hidden. */
const otherOf = (profile: Dict): Dict => {
  const out: Dict = {};
  for (const [k, v] of Object.entries(profile)) {
    if (CONSUMED.has(norm(k)) || !present(v)) continue;
    const inner = unwrap(v);
    // A wrapper object (e.g. { data: { skills, experience, hobbies } }) contributes only what is not already mapped.
    if (isObj(inner) && Object.keys(inner).some((ik) => CONSUMED.has(norm(ik)))) Object.assign(out, otherOf(inner));
    else out[k] = v;
  }
  return out;
};

export function buildProfile(root: Dict, extra: { resume?: Dict | null } = {}): Profile {
  const latestProfile = isObj(root.latest_profile) ? (root.latest_profile as Dict) : undefined;
  const nested = [root.profile, root.extracted_profile, root.parsed_profile, latestProfile].find(isObj) as Dict | undefined;
  const profile = nested ?? root;
  const get = (keys: string[], deep = true) => pick(profile, keys) ?? pick(root, keys) ?? (deep ? deepFind([profile, root], keys) : undefined);
  const resume = extra.resume ?? null;
  const metaSources = [profile.extraction, profile.meta, profile.metadata, root.extraction, root.extraction_metadata, latestProfile, resume].filter(isObj) as Dict[];
  const m = (keys: string[], deepFallback = true) => {
    for (const src of metaSources) {
      const hit = pick(src, keys);
      if (hit !== undefined) return hit;
    }
    return get(keys, deepFallback);
  };
  const firstApp = Array.isArray(root.applications) && isObj(root.applications[0]) ? (root.applications[0] as Dict) : undefined;
  const warningList = Array.from(
    new Set([
      ...texts(m(['warnings'], false)),
      ...texts(m(['parse_warnings'], false)),
      ...texts(m(['extraction_warnings'], false))
    ])
  );
  const rawOcr = m(['ocr_used'], false);
  const ocrUsed = typeof rawOcr === 'boolean' ? rawOcr : null;

  const experience = items(get(['experience', 'work_experience', 'employment', 'experiences', 'work_history', 'professional_experience', 'employment_history', 'career'])).map<Experience>((e) => {
    const start = text(pick(e, ['start_date', 'start', 'from'])); const end = text(pick(e, ['end_date', 'end', 'to']));
    const current = e.is_current === true || e.current === true || /present|current|now/i.test(end ?? '');
    const dates = text(pick(e, ['dates', 'duration', 'period'])) ?? ((start || end) ? `${start ?? ''} – ${current ? 'Present' : end ?? ''}`.trim() : null);
    return { ...base(e), title: text(pick(e, ['title', 'role', 'position', 'job_title', 'text'])), company: text(pick(e, ['company', 'organization', 'employer', 'company_name'])), location: text(e.location), dates, current, bullets: texts(pick(e, ['responsibilities', 'highlights', 'bullets', 'achievements', 'description'])) };
  });
  const education = items(get(['education', 'educations', 'education_history', 'academics', 'academic_background', 'qualifications'])).map<Education>((e) => {
    const degree = [text(pick(e, ['degree', 'qualification', 'text'])), text(pick(e, ['field', 'field_of_study', 'major']))].filter(Boolean).join(' – ') || null;
    const start = text(pick(e, ['start_date', 'start', 'from'])); const end = text(pick(e, ['end_date', 'end', 'to', 'graduation_year', 'year']));
    return { ...base(e), degree, institution: text(pick(e, ['institution', 'school', 'university', 'college'])), period: start && end ? `${start} – ${end}` : end ?? start, grade: text(pick(e, ['gpa', 'cgpa', 'grade'])), location: text(e.location) };
  });
  const projects = items(get(['projects', 'personal_projects', 'academic_projects', 'key_projects'])).map<Project>((p) => ({ ...base(p), name: text(pick(p, ['name', 'title', 'text'])), description: text(pick(p, ['description', 'summary'])), tech: techOf(pick(p, ['technologies', 'tech_stack', 'skills', 'tools', 'stack'])), url: safeUrl(text(pick(p, ['url', 'link', 'repo', 'github']))) }));
  const certifications = items(get(['certifications', 'certificates', 'licenses', 'licenses_and_certifications', 'courses', 'training'])).map<Certification>((c) => ({ ...base(c), name: text(pick(c, ['name', 'title', 'text'])), issuer: text(pick(c, ['issuer', 'issuing_organization', 'organization'])), date: text(pick(c, ['date', 'issued', 'issue_date', 'year'])), url: safeUrl(text(pick(c, ['credential_url', 'url', 'link']))) }));
  const applications = items(root.applications ?? root.job_applications).map<Application>((a) => ({ jobId: text(a.job_id), applicationId: text(a.application_id ?? a.id), jobTitle: text(a.job_title ?? a.title), status: text(a.status) }));

  const ident = [root.identity_verification, root.identity, root.verification, root.verification_detail, root.identity_hints].find(isObj) as Dict | undefined;
  const identity = ident ? {
    status: text(pick(ident, ['overall_status', 'status'])),
    checks: items(ident.checks ?? ident.hints ?? ident.signals).map((c) => ({ label: humanize(text(pick(c, ['check_type', 'type', 'name'])) ?? 'check'), status: text(c.status) ?? 'unknown', note: text(pick(c, ['signal', 'detail', 'note', 'message'])), details: isObj(c.details) ? c.details : undefined }))
  } : null;

  const yrs = text(get(['total_experience_years', 'years_of_experience', 'experience_years', 'total_experience']));
  return {
    name: text(get(['full_name', 'display_name', 'name', 'candidate_name'])), headline: text(get(['headline', 'current_title', 'current_role', 'current_position', 'professional_title', 'job_title', 'designation', 'title', 'position'], false) ?? deepFind([profile], ['headline', 'current_title', 'current_role', 'current_position', 'professional_title', 'designation'])),
    location: text(get(['location', 'city', 'address'])), email: text(get(['email'])), phone: text(get(['phone', 'mobile'])), links: linksOf(profile, root),
    summary: text(get(['summary', 'professional_summary', 'about', 'objective', 'career_objective', 'profile_summary', 'bio'])), yearsExperience: yrs,
    skills: skillsOf(get(['skills', 'technical_skills', 'skill_set', 'key_skills', 'competencies', 'core_skills', 'technologies'])), experience, education, projects, certifications, applications,
    meta: {
      confidence: num(unwrap(m(['overall_confidence', 'extraction_confidence', 'confidence'], false))),
      method: text(m(['extraction_method', 'parser_version', 'extracted_by', 'method', 'parser'], false)),
      model: text(m(['ai_model', 'model', 'llm_model', 'models'], false)),
      origin: text(m(['data_origin', 'ai_engine', 'origin', 'source'], false)),
      parseStatus: text(resume?.parse_status ?? firstApp?.resume_status),
      promptVersion: text(m(['prompt_version'], false)),
      schemaVersion: text(m(['extraction_version', 'schema_version'], false)),
      ocrUsed,
      warnings: warningList
    },
    identity, other: otherOf(profile), raw: root
  };
}
