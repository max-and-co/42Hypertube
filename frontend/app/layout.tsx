import type { Metadata } from "next";
import { Bodoni_Moda, Inter } from "next/font/google";
import "./globals.css";
import Providers from "./providers";

// Self-hosted at build time: no runtime request to Google, so nothing that can
// fail in the browser console.
const display = Bodoni_Moda({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-display",
  // 400 is the only weight the stylesheets ask for; declaring 500/700 emitted
  // 16 extra @font-face rules for nothing.
  weight: ["400"],
  style: ["normal", "italic"],
  // Preloading warns ("preloaded ... but not used within a few seconds") on any
  // page that does not paint text in that family immediately - /login never
  // uses the upright cut, and /watch paints only after its API round-trips.
  // The subject forbids console warnings, so we let the CSS request them.
  preload: false,
  // Next has no fallback metrics for this family; asking it to compute them
  // emits a build error. We supply the fallback stack ourselves instead.
  adjustFontFallback: false,
  fallback: ["Georgia", "Times New Roman", "serif"],
});

const sans = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
  preload: false,
});

export const metadata: Metadata = {
  title: "Lumière",
  description: "Stream royalty-free and public-domain cinema.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${display.variable} ${sans.variable}`}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
