import Image from "next/image";
import { cn } from "@/lib/utils/cn";

/**
 * Pratap brand assets (supplied logo, background made transparent and cropped —
 * the artwork itself is not redrawn).
 *  - full:     logo + "Carving Lives" tagline (240×240 source)
 *  - wordmark: "pratap" only (240×67)
 *  - mark:     leaf "p" icon (68×68)
 */
const ASSETS = {
  full: { src: "/brand/pratap-logo.png", w: 240, h: 240 },
  wordmark: { src: "/brand/pratap-wordmark.png", w: 240, h: 67 },
  mark: { src: "/brand/pratap-mark.png", w: 68, h: 68 },
} as const;

export function Logo({
  variant = "wordmark",
  width,
  className,
  eager,
}: {
  variant?: keyof typeof ASSETS;
  width: number;
  className?: string;
  /** Load immediately (above-the-fold logos) instead of lazily */
  eager?: boolean;
}) {
  const a = ASSETS[variant];
  const height = Math.round((width * a.h) / a.w);
  return (
    <Image
      src={a.src}
      alt="Pratap"
      width={width}
      height={height}
      loading={eager ? "eager" : "lazy"}
      style={{ width, height }}
      className={cn("select-none", className)}
      draggable={false}
    />
  );
}
