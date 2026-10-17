import type { Metadata } from "next";
import { Suspense, type ReactNode } from "react";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import { QueryProvider } from "@/components/providers/QueryProvider";
import { Shell } from "@/components/Shell";
import "./globals.css";

const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  variable: "--font-plex-sans",
  weight: ["400", "500", "600"],
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  variable: "--font-plex-mono",
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "NomadQuant",
  description: "Local paper-only status for NomadQuant",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`h-full ${plexSans.variable} ${plexMono.variable}`}>
      <body className="min-h-full antialiased">
        <QueryProvider>
          <Suspense fallback={null}>
            <Shell>{children}</Shell>
          </Suspense>
        </QueryProvider>
      </body>
    </html>
  );
}
