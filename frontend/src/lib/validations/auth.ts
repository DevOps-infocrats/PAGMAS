import { z } from "zod";

export const loginSchema = z.object({
  // the e-mail – or, for an FRT team login created without e-mail, the FRT code (no "@"; app.security.frt_login)
  email: z
    .string()
    .trim()
    .min(1, "Enter your email address or FRT code")
    .refine((v) => !v.includes("@") || z.string().email().safeParse(v).success, "Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
  remember: z.boolean(),
});

export type LoginValues = z.infer<typeof loginSchema>;
