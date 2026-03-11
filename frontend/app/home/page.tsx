"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import "./home.css";

export default function Home() {
  const [username, setUsername] = useState("");
  const router = useRouter();

  useEffect(() => {
    fetch("/api/users/me").then(async (res) => {
      if (!res.ok) {
        router.replace("/login");
      } else {
        const data = await res.json();
        setUsername(data.username);
      }
    });
  }, [router]);

  const handleLogout = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
  };

  return (
    <div className="home-page">
      <div className="vignette" />
      <div className="scanlines" />
      <div className="grain" />

      <div className="home-card f1">
        <div className="corner tl" />
        <div className="corner tr" />
        <div className="corner bl" />
        <div className="corner br" />

        <div className="home-header">
          <p className="eyebrow f2">✦ &nbsp; ANNO DOMINI MMXXV &nbsp; ✦</p>
          <h1 className="brand metallic flicker f2">LUMIÈRE</h1>
          <p className="subtitle f3">Pictures &amp; Entertainment</p>
          <hr className="divider f3" />
        </div>

        <p className="section-label f3">— Members Lounge —</p>

        {username && (
          <p className="welcome-text f4">Welcome, {username}</p>
        )}

        <p className="coming-soon f4">
          The theatre is being prepared.<br />
          Curtain rises soon.
        </p>

        <div className="f5">
          <button onClick={handleLogout} className="submit-btn">
            Leave the Theatre
          </button>
        </div>
      </div>
    </div>
  );
}
