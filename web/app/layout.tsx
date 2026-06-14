import type { Metadata } from "next";
import "@fontsource/anton/latin-400.css";
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-900.css";
import "@fontsource/lato/latin-400.css";
import "@fontsource/lato/latin-900.css";
import "@fontsource/montserrat/latin-400.css";
import "@fontsource/montserrat/latin-900.css";
import "@fontsource/open-sans/latin-400.css";
import "@fontsource/open-sans/latin-800.css";
import "@fontsource/oswald/latin-400.css";
import "@fontsource/oswald/latin-700.css";
import "@fontsource/poppins/latin-400.css";
import "@fontsource/poppins/latin-900.css";
import "@fontsource/roboto/latin-400.css";
import "@fontsource/roboto/latin-900.css";
import "./styles.css";

export const metadata: Metadata = {
  title: "VCG Content Command Center",
  description: "Local transcript editing and caption generation for creator videos",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
