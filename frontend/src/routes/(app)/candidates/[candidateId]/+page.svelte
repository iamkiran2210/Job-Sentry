<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { deleteCandidate, getCandidate, updateCandidate } from '$lib/services/directory';
  import { ApiError } from '$lib/services/api-client';
  import { toast } from '$lib/stores/toast.svelte';
  import { toastError } from '$lib/errors';
  import { confirmDialog } from '$lib/stores/confirm.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';
  import CandidateProfile from '$lib/components/profile/CandidateProfile.svelte';
  import { buildProfile } from '$lib/profile';
  import { Alert, AlertTitle, AlertDescription } from '$lib/components/ui/alert';
  import { Button } from '$lib/components/ui/button';
  import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '$lib/components/ui/card';
  import { Input } from '$lib/components/ui/input';
  import { Label } from '$lib/components/ui/label';
  import { Textarea } from '$lib/components/ui/textarea';
  import { AlertTriangle, ArrowLeft, Pencil, Trash2, Save, X, Loader2 } from '@lucide/svelte';

  const id = page.params.candidateId!;
  let c = $state<Record<string, unknown> | null>(null);
  let err = $state('');
  let editing = $state(false);
  let saving = $state(false);
  let deleting = $state(false);

  let fullName = $state('');
  let email = $state('');
  let phone = $state('');
  let location = $state('');
  let summary = $state('');
  let linkedinUrl = $state('');
  let githubUrl = $state('');
  let portfolioUrl = $state('');
  let skillsText = $state('');

  function hydrateForm(raw: Record<string, unknown>) {
    const p = buildProfile(raw);
    fullName = p.name ?? '';
    email = p.email ?? '';
    phone = p.phone ?? '';
    location = p.location ?? '';
    summary = p.summary ?? '';
    linkedinUrl = p.links.find((l) => /linkedin/i.test(l.label) || /linkedin\.com/i.test(l.url))?.url ?? '';
    githubUrl = p.links.find((l) => /github/i.test(l.label) || /github\.com/i.test(l.url))?.url ?? '';
    portfolioUrl =
      p.links.find(
        (l) =>
          /portfolio|website|web/i.test(l.label) ||
          (!/linkedin\.com|github\.com/i.test(l.url))
      )?.url ?? '';
    skillsText = p.skills.map((s) => s.name).join(', ');
  }

  getCandidate(id)
    .then((d) => {
      c = d;
      hydrateForm(d);
    })
    .catch((e) => {
      err = e instanceof ApiError ? e.message : 'Failed to load.';
      toastError(e, 'Could not load candidate');
    });

  async function saveEdits(e: SubmitEvent) {
    e.preventDefault();
    if (saving) return;
    saving = true;
    try {
      const parsedSkills = skillsText
        .split(/[,\n]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      const updated = await updateCandidate(id, {
        full_name: fullName.trim() || null,
        email: email.trim() || null,
        phone: phone.trim() || null,
        location: location.trim() || null,
        summary: summary.trim() || null,
        linkedin_url: linkedinUrl.trim() || null,
        github_url: githubUrl.trim() || null,
        portfolio_url: portfolioUrl.trim() || null,
        skills: parsedSkills
      });
      c = updated;
      hydrateForm(updated);
      editing = false;
      toast.success('Candidate details updated', 'Manual edits have been saved to the candidate profile.');
    } catch (e) {
      toastError(e, 'Could not update candidate details');
    } finally {
      saving = false;
    }
  }

  async function removeCandidate() {
    if (deleting) return;
    const pName = c ? buildProfile(c).name : null;
    const ok = await confirmDialog({
      title: `Delete ${pName ?? 'this candidate'}?`,
      message:
        'This permanently deletes the candidate profile and uploaded resumes. Past immutable ranking audit logs are preserved without personal data.',
      confirmLabel: 'Delete candidate',
      danger: true
    });
    if (!ok) return;
    deleting = true;
    try {
      await deleteCandidate(id);
      toast.success('Candidate deleted', `${pName ?? 'Candidate'} has been removed.`);
      await goto('/candidates');
    } catch (e) {
      toastError(e, 'Could not delete candidate');
      deleting = false;
    }
  }
</script>

<div class="space-y-4">
  {#if err}
    <Alert variant="destructive">
      <AlertTriangle class="size-4" />
      <AlertTitle>Cannot load candidate</AlertTitle>
      <AlertDescription class="flex items-center justify-between gap-4 mt-2">
        <span>{err}</span>
        <Button variant="outline" size="sm" href="/candidates">
          <ArrowLeft class="mr-1.5 size-3.5" /> Back to candidates
        </Button>
      </AlertDescription>
    </Alert>
  {:else if !c}
    <Skeleton rows={4} height="h-28" />
  {:else}
    <div class="flex flex-wrap items-center justify-between gap-2">
      <Button variant="ghost" size="sm" href="/candidates" class="px-2">
        <ArrowLeft class="mr-1.5 size-3.5" /> All candidates
      </Button>
      <div class="flex flex-wrap items-center gap-2">
        <Button
          variant={editing ? 'secondary' : 'outline'}
          size="sm"
          onclick={() => {
            if (!editing && c) hydrateForm(c);
            editing = !editing;
          }}
        >
          {#if editing}
            <X class="mr-1.5 size-3.5" /> Close editor
          {:else}
            <Pencil class="mr-1.5 size-3.5" /> Edit details
          {/if}
        </Button>
        <Button variant="destructive" size="sm" disabled={deleting} onclick={removeCandidate}>
          {#if deleting}
            <Loader2 class="mr-1.5 size-3.5 animate-spin" /> Deleting…
          {:else}
            <Trash2 class="mr-1.5 size-3.5" /> Delete candidate
          {/if}
        </Button>
      </div>
    </div>

    {#if editing}
      <Card class="border-border bg-card shadow-sm">
        <CardHeader>
          <CardTitle class="text-lg">Edit Candidate Details</CardTitle>
          <CardDescription>
            Manually update identity, contact links, summary, or skills. Changes sync to the candidate's latest extracted profile for future scoring and verification.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onsubmit={saveEdits} class="space-y-4">
            <div class="grid gap-4 sm:grid-cols-2">
              <div class="space-y-1.5">
                <Label for="cand-name">Full name</Label>
                <Input id="cand-name" bind:value={fullName} placeholder="e.g. Priya Sharma" />
              </div>
              <div class="space-y-1.5">
                <Label for="cand-email">Email</Label>
                <Input id="cand-email" type="email" bind:value={email} placeholder="name@example.com" />
              </div>
              <div class="space-y-1.5">
                <Label for="cand-phone">Phone</Label>
                <Input id="cand-phone" bind:value={phone} placeholder="+1 415 555 2671" />
              </div>
              <div class="space-y-1.5">
                <Label for="cand-location">Location</Label>
                <Input id="cand-location" bind:value={location} placeholder="City, Country" />
              </div>
              <div class="space-y-1.5">
                <Label for="cand-github">GitHub URL</Label>
                <Input id="cand-github" bind:value={githubUrl} placeholder="https://github.com/username" />
              </div>
              <div class="space-y-1.5">
                <Label for="cand-portfolio">Portfolio URL</Label>
                <Input id="cand-portfolio" bind:value={portfolioUrl} placeholder="https://portfolio.dev" />
              </div>
              <div class="space-y-1.5 sm:col-span-2">
                <Label for="cand-linkedin">LinkedIn URL</Label>
                <Input id="cand-linkedin" bind:value={linkedinUrl} placeholder="https://linkedin.com/in/username" />
              </div>
              <div class="space-y-1.5 sm:col-span-2">
                <Label for="cand-skills">Skills (comma-separated)</Label>
                <Input id="cand-skills" bind:value={skillsText} placeholder="Python, FastAPI, PostgreSQL, Docker, React" />
              </div>
              <div class="space-y-1.5 sm:col-span-2">
                <Label for="cand-summary">Professional Summary</Label>
                <Textarea id="cand-summary" rows={3} bind:value={summary} placeholder="Brief summary of experience and focus areas…" />
              </div>
            </div>

            <div class="flex items-center gap-2 pt-2 border-t border-border">
              <Button type="submit" size="sm" disabled={saving}>
                {#if saving}
                  <Loader2 class="mr-1.5 size-3.5 animate-spin" /> Saving…
                {:else}
                  <Save class="mr-1.5 size-3.5" /> Save changes
                {/if}
              </Button>
              <Button type="button" variant="ghost" size="sm" onclick={() => (editing = false)}>
                Cancel
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    {/if}

    <CandidateProfile data={c} />
  {/if}
</div>
