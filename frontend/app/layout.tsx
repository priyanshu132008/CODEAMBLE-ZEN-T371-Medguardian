import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import PWARegister from "@/Components/PWARegister";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// JetBrains Mono is the terminal / medical-data font: used for API routes,
// extracted model JSON, ICD-10 codes, and any monospace clinical payload where
// columnar alignment matters. It runs ALONGSIDE Geist Mono (never replaces it):
// `--font-mono` stays Geist Mono for general UI; `--font-jetbrains` is opt-in
// via the `font-jetbrains` utility / `--font-jetbrains` token for data surfaces.
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "MedGuardian — Enterprise Clinical Orchestration & TPA Claims",
  description:
    "Multi-agent AI companion for post-discharge patient care: vision OCR intake, allergy safety engine, voice teach-back verification, and instant TPA insurance dossier generation. ABDM & DPDP Act 2023 compliant.",
  applicationName: "MedGuardian",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "MedGuardian",
  },
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any", type: "image/x-icon" },
      { url: "/icon.svg", type: "image/svg+xml" },
    ],
  },
};

export const viewport: Viewport = {
  themeColor: "#0f172a",
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        {children}
        <PWARegister />
      </body>
    </html>
  );
}
