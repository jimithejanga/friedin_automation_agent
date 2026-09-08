import type { Metadata } from "next";
import "./globals.css";
import Navbar from "@/components/Navbar";
import Footer from "@/components/Footer";

export const metadata: Metadata = {
  title: "Central Motor Registry (CMR) Specialist | Ingestion & Support Portal",
  description:
    "Official Nigerian Central Motor Registry AI specialist intake and case tracking portal. Inquire about vehicular regulations, tint permits, vehicle transfer, and track official support cases.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <Navbar />
        <div style={{ flex: 1 }}>{children}</div>
        <Footer />
      </body>
    </html>
  );
}
