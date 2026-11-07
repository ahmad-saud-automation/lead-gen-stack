import type { Metadata } from "next";

import { PresentingGate } from "@/components/presenting-gate";
import { SavedNoteBar } from "@/components/saved-note";
import { USidebar } from "@/components/u-shell";
import "./globals.css";
import "./leadgen.css";
import "./ux.css";

export const metadata: Metadata = {
  title: "Lead Gen Engine",
  description: "Reads the lead sheet, finds and verifies emails, and pushes each lane to its Instantly campaign.",
};

// Every screen shows live state, so nothing here is cached.
export const dynamic = "force-dynamic";

/* Runs before the first paint, so a dark-mode user never sees a flash of the light page.
 * The saved choice wins; with none, the computer's own setting decides. Key: THEME_KEY in
 * components/shell.tsx. */
const THEME_SCRIPT = `try{var t=localStorage.getItem("leadgen:theme");if(t!=="dark"&&t!=="light")t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // the theme attribute is set by THEME_SCRIPT before React loads, so it differs on purpose
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
        {/* Loaded by link rather than next/font so a build never depends on reaching Google.
            The stack falls back to the system sans if it fails. */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Inter+Tight:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <USidebar />
        <main className="main">
          <SavedNoteBar />
          <PresentingGate>{children}</PresentingGate>
        </main>
      </body>
    </html>
  );
}
