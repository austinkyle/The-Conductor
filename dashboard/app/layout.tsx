import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "The Conductor — Observability",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          fontFamily: "system-ui, -apple-system, sans-serif",
          background: "#f8f9fa",
          color: "#111",
        }}
      >
        {children}
      </body>
    </html>
  );
}
