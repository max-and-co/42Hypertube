"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

export default function Home() {
  const [userServiceMsg, setUserServiceMsg] = useState("");
  const [torrentServiceMsg, setTorrentServiceMsg] = useState("");
  const router = useRouter();

  const testUserAuth = async () => {
    try {
      const res = await fetch("/api/users/me");
      if (res.ok) {
        const data = await res.json();
        setUserServiceMsg(`Success! Email: ${data.email}, ID: ${data.id}`);
      } else {
        setUserServiceMsg("Unauthorized. Please log in.");
      }
    } catch (err) {
      setUserServiceMsg("Error connecting to User Service");
    }
  };

  const testTorrentAuth = async () => {
    try {
      const res = await fetch("/api/torrent/protected");
      if (res.ok) {
        const data = await res.json();
        setTorrentServiceMsg(`Success! User ID: ${data.user_id}`);
      } else {
        setTorrentServiceMsg("Unauthorized. Please log in.");
      }
    } catch (err) {
      setTorrentServiceMsg("Error connecting to Torrent Service");
    }
  };

  const handleLogout = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    setUserServiceMsg("Logged out");
    setTorrentServiceMsg("Logged out");
    router.refresh();
  };

  return (
    <div className="flex flex-col min-h-screen items-center justify-center bg-gray-900 text-white p-4">
      <h1 className="text-4xl font-bold mb-8">Hypertube is Running 🚀</h1>
      
      <div className="flex gap-4 mb-12">
        <Link href="/login" className="px-6 py-2 bg-green-600 hover:bg-green-700 rounded font-semibold transition">
          Login
        </Link>
        <Link href="/register" className="px-6 py-2 bg-blue-600 hover:bg-blue-700 rounded font-semibold transition">
          Register
        </Link>
        <button onClick={handleLogout} className="px-6 py-2 bg-red-600 hover:bg-red-700 rounded font-semibold transition">
          Logout
        </button>
      </div>

      <div className="flex flex-col md:flex-row gap-8 w-full max-w-4xl">
        {/* User Service Test */}
        <div className="flex-1 bg-gray-800 p-6 rounded-lg shadow-lg text-center shadow-blue-500/20">
          <h2 className="text-2xl font-semibold mb-4 text-blue-400">User Service</h2>
          <button 
            onClick={testUserAuth}
            className="w-full py-3 mb-4 bg-gray-700 hover:bg-gray-600 rounded transition font-medium"
          >
            Test Auth (/api/users/me)
          </button>
          <div className="min-h-[60px] flex items-center justify-center text-sm bg-gray-900 rounded p-4 text-gray-300">
            {userServiceMsg || "Click to test authentication"}
          </div>
        </div>

        {/* Torrent Service Test */}
        <div className="flex-1 bg-gray-800 p-6 rounded-lg shadow-lg text-center shadow-purple-500/20">
          <h2 className="text-2xl font-semibold mb-4 text-purple-400">Torrent Service</h2>
          <button 
            onClick={testTorrentAuth}
            className="w-full py-3 mb-4 bg-gray-700 hover:bg-gray-600 rounded transition font-medium"
          >
            Test Auth (/api/torrent/protected)
          </button>
          <div className="min-h-[60px] flex items-center justify-center text-sm bg-gray-900 rounded p-4 text-gray-300">
            {torrentServiceMsg || "Click to test authentication"}
          </div>
        </div>
      </div>
    </div>
  );
}
