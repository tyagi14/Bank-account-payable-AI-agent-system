import "./globals.css";
import Nav from "./nav";
import { AuthProvider } from "../lib/auth";

export const metadata = { title: "Custodian Console" };

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <Nav />
          <main>{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
