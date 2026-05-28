"use client"

import { useState, useEffect } from "react"

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000"

interface Profile {
  name: string
  age: number | null
  preferences: string
  extra: string
}

interface Props {
  onClose: () => void
}

export default function ProfileSettings({ onClose }: Props) {
  const [profile, setProfile] = useState<Profile>({ name: "", age: null, preferences: "", extra: "" })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    fetch(`${BACKEND_URL}/profile`)
      .then(r => r.json())
      .then(data => setProfile(data))
      .catch(() => {})
  }, [])

  const save = async () => {
    setSaving(true)
    await fetch(`${BACKEND_URL}/profile`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    })
    setSaving(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <>
      <style>{`
        .modal-backdrop {
          position: fixed; inset: 0; z-index: 100;
          background: rgba(0,0,0,0.6); backdrop-filter: blur(4px);
          display: flex; align-items: center; justify-content: center;
          animation: fade-in 0.15s ease-out;
        }
        @keyframes fade-in { from{opacity:0} to{opacity:1} }
        .modal {
          background: #111118; border: 1px solid rgba(255,255,255,0.08);
          border-radius: 16px; padding: 28px; width: 420px;
          animation: modal-in 0.2s cubic-bezier(0.16,1,0.3,1);
        }
        @keyframes modal-in { from{opacity:0;transform:scale(0.96) translateY(8px)} to{opacity:1;transform:scale(1) translateY(0)} }
        .modal-title {
          font-size: 15px; font-weight: 700; color: rgba(255,255,255,0.85);
          margin-bottom: 4px; font-family: 'Syne', sans-serif;
        }
        .modal-sub {
          font-size: 12px; color: rgba(255,255,255,0.25);
          font-family: 'JetBrains Mono', monospace; margin-bottom: 24px;
        }
        .field { margin-bottom: 16px; }
        .field label {
          display: block; font-size: 11px; font-weight: 600;
          letter-spacing: 0.1em; text-transform: uppercase;
          color: rgba(255,255,255,0.3); margin-bottom: 6px;
          font-family: 'Syne', sans-serif;
        }
        .field input, .field textarea {
          width: 100%; background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08); border-radius: 8px;
          padding: 9px 12px; font-size: 13px; font-family: 'Syne', sans-serif;
          color: rgba(255,255,255,0.8); outline: none;
          transition: border-color 0.2s; resize: none;
        }
        .field input:focus, .field textarea:focus { border-color: rgba(59,130,246,0.4); }
        .field input::placeholder, .field textarea::placeholder { color: rgba(255,255,255,0.15); }
        .modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 24px; }
        .btn-cancel {
          padding: 8px 16px; border-radius: 8px; font-size: 13px;
          font-family: 'Syne', sans-serif; background: transparent;
          border: 1px solid rgba(255,255,255,0.08); color: rgba(255,255,255,0.4);
          cursor: pointer; transition: all 0.15s;
        }
        .btn-cancel:hover { border-color: rgba(255,255,255,0.15); color: rgba(255,255,255,0.7); }
        .btn-save {
          padding: 8px 20px; border-radius: 8px; font-size: 13px;
          font-family: 'Syne', sans-serif; font-weight: 600;
          background: #3b82f6; border: none; color: white;
          cursor: pointer; transition: all 0.15s;
        }
        .btn-save:hover:not(:disabled) { background: #2563eb; }
        .btn-save:disabled { opacity: 0.5; cursor: default; }
        .btn-save.saved { background: #22c55e; }
      `}</style>

      <div className="modal-backdrop" onClick={onClose}>
        <div className="modal" onClick={e => e.stopPropagation()}>
          <div className="modal-title">User Profile</div>
          <div className="modal-sub">bot sẽ nhớ thông tin này ở mọi cuộc trò chuyện</div>

          <div className="field">
            <label>Tên</label>
            <input placeholder="Stein" value={profile.name}
              onChange={e => setProfile(p => ({ ...p, name: e.target.value }))} />
          </div>

          <div className="field">
            <label>Tuổi</label>
            <input type="number" placeholder="22" value={profile.age ?? ""}
              onChange={e => setProfile(p => ({ ...p, age: e.target.value ? parseInt(e.target.value) : null }))} />
          </div>

          <div className="field">
            <label>Preferences</label>
            <textarea rows={2} placeholder="thích AI, robotics, lập trình Python..."
              value={profile.preferences}
              onChange={e => setProfile(p => ({ ...p, preferences: e.target.value }))} />
          </div>

          <div className="field">
            <label>Thông tin thêm</label>
            <textarea rows={2} placeholder="đang học fullstack AI, internship..."
              value={profile.extra}
              onChange={e => setProfile(p => ({ ...p, extra: e.target.value }))} />
          </div>

          <div className="modal-actions">
            <button className="btn-cancel" onClick={onClose}>Hủy</button>
            <button className={`btn-save ${saved ? "saved" : ""}`} onClick={save} disabled={saving}>
              {saved ? "✓ Đã lưu" : saving ? "Đang lưu..." : "Lưu"}
            </button>
          </div>
        </div>
      </div>
    </>
  )
}