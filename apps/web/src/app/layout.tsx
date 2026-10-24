import type { Metadata } from "next";
import { getServerSession } from "next-auth";
import { Sidebar } from "@/components/Sidebar";
import { ToastProvider } from "@/components/Toast";
import { devIdentity } from "@/lib/api";
import { authOptions } from "@/lib/auth";
import { config } from "@/lib/config";
import "./globals.css";

export const metadata: Metadata = {
  title: "Inventory Capture",
  description: "Receiving dock capture, review and inventory search",
};

export const dynamic = "force-dynamic";

async function identity(): Promise<{ user: string; groups: string[] }> {
  if (config.authMode === "dev") return devIdentity();
  const session = await getServerSession(authOptions);
  return { user: session?.user?.email ?? session?.user?.name ?? "", groups: session?.groups ?? [] };
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const id = await identity();
  return (
    <html lang="en">
      <body>
        <ToastProvider>
          <div className="flex min-h-screen flex-col md:flex-row">
            {id.user && <Sidebar user={id.user} groups={id.groups} authMode={config.authMode} />}
            <main className="min-w-0 flex-1 px-4 py-5 md:px-8">{children}</main>
          </div>
        </ToastProvider>
      </body>
    </html>
  );
}
