/**
 * Inline script that runs synchronously during HTML parsing (before paint).
 * The type switch avoids React's dev warning about rendering <script> on the
 * client; see Next.js "Preventing flash before hydration".
 */
export function InlineScript({ html }: { html: string }) {
  return (
    <script
      type={typeof window === "undefined" ? "text/javascript" : "text/plain"}
      suppressHydrationWarning
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
