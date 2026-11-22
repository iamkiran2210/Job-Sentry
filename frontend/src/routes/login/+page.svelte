<script lang="ts">
  import { goto } from '$app/navigation';
  import { login, loginWithGoogle } from '$lib/services/auth';
  import { toastError } from '$lib/errors';
  import { toast } from '$lib/stores/toast.svelte';
  import { GOOGLE_CLIENT_ID } from '$lib/config';
  import GoogleButton from '$lib/components/GoogleButton.svelte';
  import LogoMark from '$lib/components/LogoMark.svelte';

  import * as Form from '$lib/components/ui/form';
  import { Input } from '$lib/components/ui/input';
  import { Button } from '$lib/components/ui/button';
  import { Eye, EyeOff, Loader2 } from '@lucide/svelte';

  import { superForm, defaults } from 'sveltekit-superforms/client';
  import { zod } from 'sveltekit-superforms/adapters';
  import { z } from 'zod';

  const loginSchema = z.object({
    email: z.string().email('Please enter a valid email address'),
    password: z.string().min(1, 'Password is required')
  });

  type LoginForm = z.infer<typeof loginSchema>;

  let showPassword = $state(false);
  let pending = $state(false);

  const adapter = (zod as any)(loginSchema);
  const form = superForm<LoginForm>(defaults({ email: '', password: '' }, adapter), {
    SPA: true,
    validators: adapter,
    async onUpdate({ form }) {
      if (!form.valid) return;
      pending = true;
      try {
        const data = form.data as LoginForm;
        await login(data.email.trim(), data.password);
        await goto('/dashboard');
      } catch (err) {
        toastError(err, 'Sign-in failed');
      } finally {
        pending = false;
      }
    }
  });

  const { form: formData, enhance } = form;

  async function runGoogle(token: string) {
    if (pending) return;
    pending = true;
    try {
      await loginWithGoogle(token);
      await goto('/dashboard');
    } catch (err) {
      toastError(err, 'Google sign-in failed');
    } finally {
      pending = false;
    }
  }
</script>

<main class="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
  <!-- Left Brand Presentation Section -->
  <section class="hidden flex-col justify-between bg-sidebar p-16 text-sidebar-foreground lg:flex">
    <div class="flex items-center">
      <LogoMark variant="white" class="h-14 w-auto" />
    </div>

    <div class="space-y-6 max-w-xl">
      <h1 class="text-4xl font-extrabold leading-tight tracking-tight text-white sm:text-5xl">
        AI-Powered <span class="text-accent">Recruitment Intelligence</span>
      </h1>
      <p class="text-lg text-sidebar-foreground/80 leading-relaxed">
        Analyze resumes, match skills, and rank applicants with explainable AI. Every decision stays with you.
      </p>
    </div>

    <div></div>
  </section>

  <!-- Right Form Section -->
  <section class="flex items-center justify-center p-6 sm:p-12 bg-background">
    <div class="w-full max-w-md space-y-8 rounded-2xl border border-border bg-card p-8 sm:p-10 shadow-sm">
      <div class="space-y-2">
        <div class="lg:hidden flex items-center mb-4">
          <LogoMark variant="black" class="h-11 w-auto" />
        </div>
        <h2 class="text-2xl font-bold tracking-tight text-foreground">Welcome back</h2>
        <p class="text-sm text-muted-foreground">Sign in to your recruiter account to continue</p>
      </div>

      {#if GOOGLE_CLIENT_ID}
        <div class="space-y-4">
          <GoogleButton
            onCredential={(t) => runGoogle(t)}
            onError={(m) => toast.error('Google sign-in failed', m)}
          />
          <div class="relative flex items-center justify-center">
            <div class="absolute inset-0 flex items-center"><div class="w-full border-t border-border"></div></div>
            <span class="relative bg-card px-3 text-xs uppercase text-muted-foreground">or continue with email</span>
          </div>
        </div>
      {/if}

      <form method="POST" use:enhance class="space-y-5">
        <Form.Field {form} name="email">
          <Form.Control>
            {#snippet children({ props })}
              <Form.Label>Email address</Form.Label>
              <Input
                {...props}
                type="email"
                autocomplete="email"
                placeholder="recruiter@company.com"
                bind:value={$formData.email}
              />
            {/snippet}
          </Form.Control>
          <Form.FieldErrors class="text-xs text-destructive" />
        </Form.Field>

        <Form.Field {form} name="password">
          <Form.Control>
            {#snippet children({ props })}
              <Form.Label>Password</Form.Label>
              <div class="relative">
                <Input
                  {...props}
                  type={showPassword ? 'text' : 'password'}
                  autocomplete="current-password"
                  placeholder="••••••••"
                  bind:value={$formData.password}
                  class="pr-10"
                />
                <button
                  type="button"
                  onclick={() => (showPassword = !showPassword)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  {#if showPassword}
                    <EyeOff class="size-4" />
                  {:else}
                    <Eye class="size-4" />
                  {/if}
                </button>
              </div>
            {/snippet}
          </Form.Control>
          <Form.FieldErrors class="text-xs text-destructive" />
        </Form.Field>

        <Button type="submit" disabled={pending} class="w-full font-medium">
          {#if pending}
            <Loader2 class="mr-2 size-4 animate-spin" />
            Signing in…
          {:else}
            Sign in
          {/if}
        </Button>
      </form>

      <p class="text-center text-sm text-muted-foreground">
        New here?
        <a href="/register" class="font-medium text-primary hover:underline">Create an account</a>
      </p>
    </div>
  </section>
</main>
