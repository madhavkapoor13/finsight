import "./globals.css";

export const metadata = {
  title: "FinSight",
  description: "Financial report analysis workspace"
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
