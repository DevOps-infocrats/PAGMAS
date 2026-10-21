import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import { InlineScript } from "@/components/brand/inline-script";
import { Preloader } from "@/components/brand/preloader";
import { NavigationProgressProvider } from "@/components/layout/navigation-progress";
import { ThemeProvider } from "@/components/providers/theme-provider";
import { THEME_INIT_SCRIPT } from "@/lib/theme";
import { TooltipProvider } from "@/components/ui/overlays";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: { default: "Pratap · Network Analytics", template: "%s · Pratap Network Analytics" },
  description: "Fibre network operations and analytics dashboard.",
  icons: { icon: "/brand/pratap-mark.png" },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f7f9" },
    { media: "(prefers-color-scheme: dark)", color: "#0c1015" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <body className="min-h-dvh">
        <InlineScript html={THEME_INIT_SCRIPT} />
        <Preloader />
        <ThemeProvider>
          <TooltipProvider>
            <NavigationProgressProvider>{children}</NavigationProgressProvider>
          </TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
