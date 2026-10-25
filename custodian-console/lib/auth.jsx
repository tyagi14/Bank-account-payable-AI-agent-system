"use client";
import Keycloak from "keycloak-js";
import { createContext, useContext, useEffect, useState } from "react";

const AuthContext = createContext({ user: null, token: null, login() {}, logout() {} });
let keycloak;

export function AuthProvider({ children }) {
  const [state, setState] = useState({ user: null, token: null });

  useEffect(() => {
    keycloak ??= new Keycloak({
      url: process.env.NEXT_PUBLIC_KEYCLOAK_URL || "http://localhost:18081",
      realm: "custodian",
      clientId: "custodian-console",
    });
    const sync = () => setState(keycloak.authenticated
      ? { user: { name: keycloak.tokenParsed.preferred_username, roles: keycloak.tokenParsed.realm_access?.roles || [] }, token: keycloak.token }
      : { user: null, token: null });
    keycloak.onAuthSuccess = keycloak.onAuthRefreshSuccess = keycloak.onAuthLogout = sync;
    keycloak.onTokenExpired = () => keycloak.updateToken(30).catch(() => keycloak.logout());
    if (!keycloak.didInitialize) keycloak.init({ onLoad: "check-sso", pkceMethod: "S256", checkLoginIframe: false }).then(sync).catch(console.error);
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, login: () => keycloak.login(), logout: () => keycloak.logout({ redirectUri: window.location.origin }) }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
