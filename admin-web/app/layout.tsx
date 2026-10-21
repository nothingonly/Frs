import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AdminProvider } from "@/components/admin-provider";
import { AdminShell } from "@/components/admin-shell";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "FRS Admin",
    template: "%s · FRS Admin",
  },
  description: "Administrative console for the FRS face recognition attendance system.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <AdminProvider>
          <AdminShell>{children}</AdminShell>
        </AdminProvider>
      </body>
    </html>
  );
}
