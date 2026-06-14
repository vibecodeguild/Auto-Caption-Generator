import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "VCG AutoCaption",
  description: "Local transcript editing and caption generation for creator videos",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
