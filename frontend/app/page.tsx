"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getSessionUser } from "./lib/api";

export default function Root() {
  const router = useRouter();

  useEffect(() => {
    getSessionUser().then((user) => router.replace(user ? "/home" : "/login"));
  }, [router]);

  return null;
}
