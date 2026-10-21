"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle, Eye, EyeOff, Loader2, ShieldAlert } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/controls";
import { Input, Label } from "@/components/ui/primitives";
import { Tooltip } from "@/components/ui/overlays";
import { IS_LIVE } from "@/lib/api";
import { signIn } from "@/lib/auth/session";
import { loginSchema, type LoginValues } from "@/lib/validations/auth";

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [showPassword, setShowPassword] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [forgotOpen, setForgotOpen] = useState(false);

  const {
    register,
    handleSubmit,
    setValue,
    control,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "", remember: true },
  });

  const remember = useWatch({ control, name: "remember" });

  const onSubmit = async (values: LoginValues) => {
    setFormError(null);
    try {
      await signIn(values.email, values.password, values.remember);
      const next = params.get("next");
      // Only allow internal dashboard paths (prevents open redirects via ?next=).
      const safe = next && /^\/dashboard(\/[\w-]*)*(\?[^\s]*)?$/.test(next) ? next : "/dashboard";
      router.replace(safe);
      router.refresh();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Sign-in failed. Please try again.");
    }
  };

  return (
    <div className="mt-8 space-y-6">
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
        {params.get("expired") === "1" && !formError && (
          <div role="status" className="rounded-md border border-border bg-muted px-3 py-2.5 text-sm text-muted-foreground">
            Your session has ended. Please sign in again.
          </div>
        )}
        {formError && (
          <div role="alert" className="flex items-start gap-2 rounded-md border border-critical/30 bg-critical-soft px-3 py-2.5 text-sm text-critical-text">
            <AlertCircle className="mt-0.5 size-4 shrink-0" />
            {formError}
          </div>
        )}

        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            autoComplete="username"
            placeholder="name@company.com"
            aria-invalid={!!errors.email}
            aria-describedby={errors.email ? "email-error" : undefined}
            {...register("email")}
          />
          {errors.email && (
            <p id="email-error" className="text-xs text-critical-text">
              {errors.email.message}
            </p>
          )}
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <Label htmlFor="password">Password</Label>
            <button type="button" onClick={() => setForgotOpen((o) => !o)} className="text-xs font-medium text-primary hover:underline">
              Forgot password?
            </button>
          </div>
          <div className="relative">
            <Input
              id="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              className="pr-10"
              aria-invalid={!!errors.password}
              aria-describedby={errors.password ? "password-error" : undefined}
              {...register("password")}
            />
            <button
              type="button"
              onClick={() => setShowPassword((s) => !s)}
              aria-label={showPassword ? "Hide password" : "Show password"}
              aria-pressed={showPassword}
              className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-1.5 text-muted-foreground hover:text-foreground"
            >
              {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </div>
          {errors.password && (
            <p id="password-error" className="text-xs text-critical-text">
              {errors.password.message}
            </p>
          )}
          {forgotOpen && (
            <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground" role="status">
              {IS_LIVE
                ? "Please contact your administrator – they can reset your password from Settings."
                : "Password reset is not available in demo mode."}
            </p>
          )}
        </div>

        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <Checkbox checked={remember} onCheckedChange={(v) => setValue("remember", v === true)} aria-label="Remember me" />
          Remember me for 7 days
        </label>

        <Button type="submit" variant="primary" size="lg" className="w-full" disabled={isSubmitting}>
          {isSubmitting && <Loader2 className="animate-spin" />}
          {isSubmitting ? "Signing in…" : "Sign in"}
        </Button>
      </form>

      {!IS_LIVE && (
      <div className="rounded-lg border border-dashed border-warning/60 bg-warning-soft/50 p-4">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-warning-text">
          <ShieldAlert className="size-4" /> Demo accounts
          <Tooltip content="Demo sign-in for mock mode only. Real authentication is done by the Python backend (live mode).">
            <span className="cursor-help font-normal normal-case tracking-normal underline decoration-dotted">why?</span>
          </Tooltip>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Demo accounts are configured on the server in <code>frontend/.env.local</code> (<code>DEMO_USERS</code>) – no password is stored in the app.
        </p>
      </div>
      )}
    </div>
  );
}
