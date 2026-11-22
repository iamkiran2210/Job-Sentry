<script lang="ts">
  import { Badge } from '$lib/components/ui/badge';
  import { humanize } from '$lib/utils';

  let { status, class: className }: { status: string; class?: string } = $props();

  const variantMap: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
    active: 'default',
    draft: 'secondary',
    paused: 'outline',
    closed: 'secondary',
    archived: 'secondary',
    rejected: 'destructive',
    shortlisted: 'default',
    hired: 'default',
    under_review: 'outline',
    offered: 'default'
  };

  const colorStyles: Record<string, string> = {
    active: 'bg-emerald-500/10 text-emerald-700 border-emerald-200 hover:bg-emerald-500/20',
    paused: 'bg-amber-500/10 text-amber-700 border-amber-200 hover:bg-amber-500/20',
    draft: 'bg-slate-100 text-slate-800 border-slate-300',
    archived: 'bg-slate-100 text-slate-800 border-slate-300',
    closed: 'bg-slate-200 text-slate-800 border-slate-300',
    rejected: 'bg-rose-500/10 text-rose-700 border-rose-200',
    shortlisted: 'bg-blue-500/10 text-blue-700 border-blue-200',
    hired: 'bg-emerald-500/15 text-emerald-800 border-emerald-300 font-semibold',
    under_review: 'bg-sky-500/10 text-sky-700 border-sky-200'
  };
</script>

<!-- Text label always shown, so status never relies on color alone. -->
<Badge variant={variantMap[status] ?? 'secondary'} class={`${colorStyles[status] ?? ''} ${className ?? ''}`}>
  {humanize(status)}
</Badge>
