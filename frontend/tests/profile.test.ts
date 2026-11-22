import { describe, expect, it } from 'vitest';
import { buildProfile } from '$lib/profile';

describe('buildProfile', () => {
  it('reads plain and value-wrapped fields without exposing wrappers', () => {
    const p = buildProfile({ full_name: 'Arjun Mehta', profile: { headline: { value: 'ML Engineer', confidence: 0.9, evidence: 'x' }, location: 'Hyderabad', total_experience_years: { value: 3 } } });
    expect(p.name).toBe('Arjun Mehta'); expect(p.headline).toBe('ML Engineer'); expect(p.yearsExperience).toBe('3');
  });
  it('groups skills from strings, objects and category maps, deduplicated', () => {
    expect(buildProfile({ profile: { skills: ['Python', 'python', { name: 'SQL', category: 'Data' }] } }).skills).toEqual([{ name: 'Python', category: 'Skills' }, { name: 'SQL', category: 'Data' }]);
    const g = buildProfile({ profile: { skills: { programming_languages: ['Rust', 'Go'], tools: [{ name: 'Docker' }] } } }).skills;
    expect(g.map((s) => [s.name, s.category])).toEqual([['Rust', 'Programming languages'], ['Go', 'Programming languages'], ['Docker', 'Tools']]);
  });
  it('builds experience with dates, current flag, bullets and keeps evidence separate', () => {
    const e = buildProfile({ profile: { experience: [{ title: 'MLE', company: 'BluePeak', start_date: 'Jul 2023', end_date: 'Present', responsibilities: ['A', 'B'], evidence: [{ text: 'line from resume' }], confidence: 1 }] } }).experience[0];
    expect(e).toMatchObject({ title: 'MLE', company: 'BluePeak', current: true, dates: 'Jul 2023 – Present', bullets: ['A', 'B'], evidence: ['line from resume'], confidence: 1 });
  });
  it('projects, certifications, education and meta', () => {
    const p = buildProfile({ extraction: { extraction_confidence: 1, extracted_by: 'pdf_text', ai_model: 'gemini', warnings: [] }, profile: {
      projects: [{ name: 'Tickets', description: 'NLP', technologies: ['NLP', 'TF-IDF'], url: 'github.com/a/b' }],
      certifications: [{ name: 'AWS CCP', issuer: 'AWS' }], education: [{ degree: 'B.Tech', field_of_study: 'CSE', institution: 'EIT', start_date: '2020', end_date: '2024', cgpa: '8.4' }] } });
    expect(p.projects[0]).toMatchObject({ name: 'Tickets', tech: ['NLP', 'TF-IDF'], url: 'https://github.com/a/b' });
    expect(p.certifications[0].issuer).toBe('AWS'); expect(p.education[0]).toMatchObject({ degree: 'B.Tech – CSE', period: '2020 – 2024', grade: '8.4' });
    expect(p.meta).toMatchObject({ confidence: 1, method: 'pdf_text', model: 'gemini', warnings: [] });
  });
  it('only allows http(s) links and tolerates empty data', () => {
    expect(buildProfile({ profile: { links: { linkedin: 'javascript:alert(1)', github: 'github.com/x' } } }).links.map((l) => l.url)).toEqual(['https://github.com/x']);
    const e = buildProfile({});
    expect(e.skills).toEqual([]); expect(e.experience).toEqual([]); expect(e.name).toBeNull();
  });
  it('finds sections nested under other keys, with odd names, strings and comma-separated skills', () => {
    const q = buildProfile({ display_name: 'SOPHIA BROWN', profile: { data: { 'Technical Skills': 'Python, SQL, Docker; Kubernetes', 'Work Experience': [{ position: 'Backend Engineer', employer: 'Acme', duration: '2021 - Present', description: 'Built APIs\nImproved latency' }], Education: ['B.Sc Computer Science, State University, 2020'], 'Personal Projects': [{ title: 'Chat app', tech_stack: 'Rust, Svelte' }], Hobbies: ['Chess'] } } });
    expect(q.skills.map((s) => s.name)).toEqual(['Python', 'SQL', 'Docker', 'Kubernetes']);
    expect(q.experience[0]).toMatchObject({ title: 'Backend Engineer', company: 'Acme', dates: '2021 - Present', bullets: ['Built APIs', 'Improved latency'] });
    expect(q.education[0].degree).toBe('B.Sc Computer Science, State University, 2020');
    expect(q.projects[0]).toMatchObject({ name: 'Chat app', tech: ['Rust', 'Svelte'] });
    expect(q.other).toEqual({ Hobbies: ['Chess'] }); // wrapper unwrapped, nothing duplicated
  });
  it('never hides unmapped data', () => {
    const q = buildProfile({ profile: { hobbies: ['Chess'], extraction: { confidence: 1 }, skills: ['Go'] } });
    expect(q.other).toEqual({ hobbies: ['Chess'] });
  });
  it('populates extraction metadata from resume_detail and latest_profile shapes', () => {
    const fromAnalysis = buildProfile(
      { display_name: 'Priya', profile: { skills: [{ name: 'Python' }] } },
      {
        resume: {
          parse_status: 'completed',
          overall_confidence: 0.87,
          extraction_method: 'pdf_text',
          ai_engine: 'pydantic_ai',
          ai_model: 'google:gemini-2.5-flash',
          prompt_version: 'v1',
          extraction_version: 1,
          ocr_used: false,
          warnings: ['minor_layout_warning']
        }
      }
    );
    expect(fromAnalysis.meta).toMatchObject({
      confidence: 0.87,
      method: 'pdf_text',
      model: 'google:gemini-2.5-flash',
      origin: 'pydantic_ai',
      parseStatus: 'completed',
      promptVersion: 'v1',
      schemaVersion: '1',
      ocrUsed: false,
      warnings: ['minor_layout_warning']
    });

    const fromCandidate = buildProfile({
      full_name: 'Priya',
      applications: [{ application_id: 'a1', resume_status: 'completed' }],
      latest_profile: {
        overall_confidence: 0.92,
        extraction_method: 'docx',
        ai_engine: 'pydantic_ai',
        ai_model: 'heuristic',
        prompt_version: 'v2',
        schema_version: 1,
        ocr_used: false,
        warnings: ['short_summary'],
        data: { skills: [{ name: 'Python' }] }
      }
    });
    expect(fromCandidate.meta).toMatchObject({
      confidence: 0.92,
      method: 'docx',
      model: 'heuristic',
      origin: 'pydantic_ai',
      parseStatus: 'completed',
      promptVersion: 'v2',
      schemaVersion: '1',
      ocrUsed: false,
      warnings: ['short_summary']
    });
    expect(fromCandidate.other).toEqual({});
  });
});
