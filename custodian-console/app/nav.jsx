"use client";
import Link from "next/link";
import { useAuth } from "../lib/auth";

export default function Nav() {
  const { user, login, logout } = useAuth();
  return (
    <nav>
      <span className="brand">Custodian</span>
      <Link href="/">Pipeline</Link>
      <Link href="/approvals">Approval queue</Link>
      <Link href="/audit">Audit log</Link>
      <Link href="/ledger">Ledger &amp; cost</Link>
      <Link href="/killswitch">Kill switch</Link>
      <Link href="/policies">Policies</Link>
      <span className="spacer" />
      {user ? (<><span>{user.name} ({user.roles.filter((r) => ["ap_clerk", "finance_controller", "cfo"].includes(r)).join(", ")})</span>
        <button className="secondary" onClick={logout}>Log out</button></>) : <button onClick={login}>Log in</button>}
    </nav>
  );
}
